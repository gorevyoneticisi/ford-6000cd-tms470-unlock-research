// esp32_slcan - SLCAN (Lawicel) USB-CAN adapter for ESP32 + SN65HVD230
//
// Turns an ESP32 DevKit with an SN65HVD230 (VP230) 3.3V CAN transceiver into a
// standard SLCAN serial adapter so the PC can drive it with python-can's "slcan"
// backend and can-isotp for UDS/ISO-TP probing.
//
// Wiring (ESP32 DevKit  ->  SN65HVD230 / VP230 blue module):
//   GPIO21 (TWAI TX) -> CTX / D   (driver input)
//   GPIO22 (TWAI RX) -> CRX / R   (receiver output)
//   3V3              -> 3V3  (the SN65HVD230 is a 3.3V part, do NOT use 5V)
//   GND              -> GND
//   CANH/CANL        -> target bus (Ford MS-CAN, 125 kbit/s)
//   module Rs        -> GND via 0 ohm for high-speed, or leave as the module wires it
//
// Serial: 115200 8N1 over the USB CP2102. Line ending: CR (\r), as SLCAN requires.
//
// SLCAN command subset implemented (enough for python-can slcan + manual use):
//   O   open channel (normal)              C   close channel
//   L   open channel listen-only (silent)  l   (alias) listen-only
//   Sn  set bitrate by standard code       s   custom (not supported -> error)
//   tIIILDD..   transmit standard (11-bit) frame
//   TIIIIIIIILDD.. transmit extended (29-bit) frame
//   rIIIL / RIIIIIIIIL   remote-request frames
//   V   firmware/hardware version    N  serial number    F  read+clear status flags
//   Z0/Z1 timestamp off/on (ms, 4 hex appended to rx frames)
// Replies: CR (0x0D) = OK, BELL (0x07) = error. Received frames echoed in t/T form.
//
// Bitrate codes (S): S0=10k S1=20k S2=50k S3=100k S4=125k S5=250k S6=500k S7=800k S8=1000k
// Default is S4 = 125 kbit/s to match Ford MS-CAN.

#include "driver/twai.h"

static const gpio_num_t TWAI_TX_PIN = GPIO_NUM_21;
static const gpio_num_t TWAI_RX_PIN = GPIO_NUM_22;
static const int        LED_PIN     = 2;      // on-board LED on most DevKits

// Passive SCI/UART sniffer. GPIO34/35 are INPUT-ONLY pins, so they can never
// drive the radio's TX line - a safe listen-only tap. GPIO34 taps the chip's
// SCI1TX (radio pin 31) -> reported as "@1" lines; GPIO35 taps SCI2TX (pin 34)
// -> "@2". Uses hardware UART1/UART2 (Serial1/Serial2), independent of the CAN
// (TWAI) peripheral, so sniffing and CAN run at the same time.
static const int        SCI1_RX_PIN = 34;
static const int        SCI2_RX_PIN = 35;
static bool             g_sciOn     = false;

static bool    g_open       = false;
static bool    g_listenOnly = false;
static bool    g_timestamp  = false;
static int     g_bitcode    = 4;              // S4 = 125k
static uint8_t g_status     = 0;              // SLCAN status flags, cleared by 'F'
static bool    g_keepalive  = false;          // K1: auto-send a frame to keep the bus (and a
static unsigned long g_ka_last = 0;           //     sleepy ECU) awake, independent of PC timing

static char    g_line[64];
static uint8_t g_len = 0;

static inline uint8_t hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return 0xFF;
}
static char nib(uint8_t v) { return v < 10 ? ('0' + v) : ('A' + v - 10); }

static void ok()  { Serial.write('\r'); }
static void err() { Serial.write('\x07'); }

static bool timingForCode(int code, twai_timing_config_t *out) {
  switch (code) {
    case 3:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_100KBITS();  *out = t; return true; }
    case 4:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_125KBITS();  *out = t; return true; }
    case 5:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_250KBITS();  *out = t; return true; }
    case 6:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_500KBITS();  *out = t; return true; }
    case 7:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_800KBITS();  *out = t; return true; }
    case 8:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_1MBITS();    *out = t; return true; }
    case 0: case 1: case 2:
             { twai_timing_config_t t = TWAI_TIMING_CONFIG_125KBITS();  *out = t; return true; } // low rates unsupported -> 125k
    default: return false;
  }
}

// Self-test: prove the ESP32 <-> SN65HVD230 TX/RX chain without another node.
// Uses NO_ACK mode + a self-reception frame, which loops the frame back through
// the transceiver. PASS means our adapter electronics and wiring to the ESP32
// are good, so any lack of bus traffic is the remote node being silent, not us.
static void selfTest() {
  if (g_open) { twai_stop(); twai_driver_uninstall(); g_open = false; }
  twai_timing_config_t t_config;
  timingForCode(g_bitcode, &t_config);
  twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT(TWAI_TX_PIN, TWAI_RX_PIN, TWAI_MODE_NO_ACK);
  twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  if (twai_driver_install(&g, &t_config, &f) != ESP_OK) { Serial.print("YFAIL install\r"); return; }
  if (twai_start() != ESP_OK) { twai_driver_uninstall(); Serial.print("YFAIL start\r"); return; }
  twai_message_t tx = {};
  tx.identifier = 0x123; tx.data_length_code = 4; tx.self = 1;
  tx.data[0] = 0xDE; tx.data[1] = 0xAD; tx.data[2] = 0xBE; tx.data[3] = 0xEF;
  bool txok = (twai_transmit(&tx, pdMS_TO_TICKS(100)) == ESP_OK);
  bool rxok = false; twai_message_t rx = {};
  if (txok) rxok = (twai_receive(&rx, pdMS_TO_TICKS(100)) == ESP_OK);
  twai_stop(); twai_driver_uninstall();
  if (txok && rxok)
    Serial.printf("YPASS id=%03X dlc=%d %02X%02X%02X%02X\r",
                  (unsigned)rx.identifier, rx.data_length_code,
                  rx.data[0], rx.data[1], rx.data[2], rx.data[3]);
  else
    Serial.printf("YFAIL tx=%d rx=%d\r", (int)txok, (int)rxok);
}

// Window probe: continuously transmit in NORMAL mode and report, live, whether
// frames are being ACKed. A CAN ACK is produced automatically by any powered,
// initialised controller on the bus, so if 'ack' ever rises above 0 during a
// radio power-up, the bootloader's CAN is alive in that window at this bitrate.
// Runs until any serial byte arrives. Reports "ack=N fail=N" every 150 ms, and
// prints "ACK!" the first time an ACK is seen.
static void probeWindow() {
  if (g_open) { twai_stop(); twai_driver_uninstall(); g_open = false; }
  twai_timing_config_t t_config;
  timingForCode(g_bitcode, &t_config);
  twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT(TWAI_TX_PIN, TWAI_RX_PIN, TWAI_MODE_NORMAL);
  twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  if (twai_driver_install(&g, &t_config, &f) != ESP_OK) { Serial.print("GFAIL install\r"); return; }
  if (twai_start() != ESP_OK) { twai_driver_uninstall(); Serial.print("GFAIL start\r"); return; }
  twai_reconfigure_alerts(TWAI_ALERT_TX_SUCCESS | TWAI_ALERT_TX_FAILED | TWAI_ALERT_BUS_OFF, NULL);
  Serial.print("Gprobe start (any byte stops)\r");
  unsigned long acks = 0, fails = 0, lastReport = millis();
  bool announced = false;
  while (!Serial.available()) {
    twai_message_t m = {};
    m.identifier = 0x7FF; m.data_length_code = 1; m.data[0] = 0x00;
    twai_transmit(&m, pdMS_TO_TICKS(5));
    uint32_t alerts = 0;
    if (twai_read_alerts(&alerts, pdMS_TO_TICKS(8)) == ESP_OK) {
      if (alerts & TWAI_ALERT_TX_SUCCESS) {
        acks++;
        if (!announced) { Serial.printf("ACK! after %lu fails\r", fails); announced = true; }
      }
      if (alerts & TWAI_ALERT_TX_FAILED) fails++;
      if (alerts & TWAI_ALERT_BUS_OFF) twai_initiate_recovery();
    }
    if (millis() - lastReport > 150) {
      Serial.printf("ack=%lu fail=%lu\r", acks, fails);
      lastReport = millis();
    }
  }
  while (Serial.available()) Serial.read();
  twai_stop(); twai_driver_uninstall();
  Serial.printf("Gdone ack=%lu fail=%lu\r", acks, fails);
}

// Measure a sniffed UART's baud by timing its shortest bit. The line idles high;
// during traffic the minimum low or high run is ~= one bit time, so baud ~=
// 1e6/minpulse. Generate activity during the 5 s window (power-cycle the radio
// so its boot banner, if any, drives the line; or trigger 10 02 over CAN).
static void measureBaud(int pin) {
  pinMode(pin, INPUT);
  unsigned long mn = 1000000UL;
  Serial.printf("Bmeasure GPIO%d: make the line active for 5s...\r", pin);
  unsigned long tend = millis() + 5000;
  while (millis() < tend) {
    unsigned long lo = pulseIn(pin, LOW, 30000);
    if (lo > 3 && lo < mn) mn = lo;
    unsigned long hi = pulseIn(pin, HIGH, 30000);
    if (hi > 3 && hi < mn) mn = hi;
  }
  if (mn < 1000000UL) {
    long raw = 1000000L / (long)mn;
    const long stdb[] = {9600,10400,19200,38400,57600,115200,230400,250000,460800,921600};
    long best = stdb[0], bd = 2000000000L;
    for (long b : stdb) { long d = b > raw ? b - raw : raw - b; if (d < bd) { bd = d; best = b; } }
    Serial.printf("Bresult GPIO%d minpulse=%luus raw~%ld snap=%ld\r", pin, mn, raw, best);
  } else {
    Serial.printf("Bresult GPIO%d no activity seen\r", pin);
  }
}

static void closeChannel() {
  if (g_open) {
    twai_stop();
    twai_driver_uninstall();
    g_open = false;
  }
}

static bool openChannel(bool listenOnly) {
  closeChannel();
  twai_timing_config_t t_config;
  if (!timingForCode(g_bitcode, &t_config)) return false;

  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(
      TWAI_TX_PIN, TWAI_RX_PIN,
      listenOnly ? TWAI_MODE_LISTEN_ONLY : TWAI_MODE_NORMAL);
  g_config.rx_queue_len = 64;
  g_config.tx_queue_len = 32;
  twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

  if (twai_driver_install(&g_config, &t_config, &f_config) != ESP_OK) return false;
  if (twai_start() != ESP_OK) { twai_driver_uninstall(); return false; }
  g_open = true;
  g_listenOnly = listenOnly;
  return true;
}

// Parse and send a t/T/r/R transmit command. Returns true on success.
static bool handleTransmit(const char *s, uint8_t n) {
  bool ext    = (s[0] == 'T' || s[0] == 'R');
  bool remote = (s[0] == 'r' || s[0] == 'R');
  uint8_t idHex = ext ? 8 : 3;
  if (n < (uint8_t)(1 + idHex + 1)) return false;   // cmd + id + dlc

  uint32_t id = 0;
  for (uint8_t i = 0; i < idHex; i++) {
    uint8_t h = hexNibble(s[1 + i]);
    if (h == 0xFF) return false;
    id = (id << 4) | h;
  }
  uint8_t dlc = hexNibble(s[1 + idHex]);
  if (dlc == 0xFF || dlc > 8) return false;

  twai_message_t msg = {};
  msg.identifier = id;
  msg.extd = ext ? 1 : 0;
  msg.rtr  = remote ? 1 : 0;
  msg.data_length_code = dlc;

  if (!remote) {
    uint8_t need = 1 + idHex + 1 + dlc * 2;
    if (n < need) return false;
    for (uint8_t i = 0; i < dlc; i++) {
      uint8_t hi = hexNibble(s[1 + idHex + 1 + i * 2]);
      uint8_t lo = hexNibble(s[1 + idHex + 2 + i * 2]);
      if (hi == 0xFF || lo == 0xFF) return false;
      msg.data[i] = (hi << 4) | lo;
    }
  }
  if (!g_open || g_listenOnly) return false;
  return twai_transmit(&msg, pdMS_TO_TICKS(50)) == ESP_OK;
}

static void emitFrame(const twai_message_t *m) {
  char out[40];
  uint8_t p = 0;
  out[p++] = m->extd ? (m->rtr ? 'R' : 'T') : (m->rtr ? 'r' : 't');
  if (m->extd) {
    for (int i = 7; i >= 0; i--) out[p++] = nib((m->identifier >> (i * 4)) & 0xF);
  } else {
    for (int i = 2; i >= 0; i--) out[p++] = nib((m->identifier >> (i * 4)) & 0xF);
  }
  out[p++] = nib(m->data_length_code & 0xF);
  if (!m->rtr) {
    for (int i = 0; i < m->data_length_code; i++) {
      out[p++] = nib((m->data[i] >> 4) & 0xF);
      out[p++] = nib(m->data[i] & 0xF);
    }
  }
  if (g_timestamp) {
    uint16_t ts = (uint16_t)(millis() & 0xFFFF);
    for (int i = 3; i >= 0; i--) out[p++] = nib((ts >> (i * 4)) & 0xF);
  }
  out[p++] = '\r';
  Serial.write((const uint8_t *)out, p);
}

static void handleLine(char *s, uint8_t n) {
  if (n == 0) { ok(); return; }   // bare CR
  switch (s[0]) {
    case 'O': if (openChannel(false)) ok(); else err(); break;
    case 'L': case 'l': if (openChannel(true)) ok(); else err(); break;
    case 'C': closeChannel(); ok(); break;
    case 'S': {
      if (n >= 2 && s[1] >= '0' && s[1] <= '8') { g_bitcode = s[1] - '0'; ok(); }
      else err();
      break;
    }
    case 's': err(); break;                       // custom BTR not supported
    case 't': case 'T': case 'r': case 'R':
      if (handleTransmit(s, n)) { Serial.write(s[0] == 't' || s[0] == 'r' ? 'z' : 'Z'); ok(); }
      else err();
      break;
    case 'V': Serial.print("V0101"); ok(); break; // version 1.01
    case 'N': Serial.print("NTMB2"); ok(); break; // pseudo serial
    case 'F': { char b[4]; b[0]='F'; b[1]=nib((g_status>>4)&0xF); b[2]=nib(g_status&0xF); Serial.write((const uint8_t*)b,3); g_status=0; ok(); break; }
    case 'Z': if (n >= 2 && (s[1]=='0'||s[1]=='1')) { g_timestamp = (s[1]=='1'); ok(); } else err(); break;
    case 'K': if (n >= 2 && (s[1]=='0'||s[1]=='1')) { g_keepalive = (s[1]=='1'); ok(); } else err(); break;
    case 'Y': selfTest(); break;                  // adapter TX/RX loopback self-test
    case 'G': probeWindow(); break;               // continuous TX, live ACK detection
    case 'B': measureBaud((n >= 2 && s[1] == '2') ? SCI2_RX_PIN : SCI1_RX_PIN); break;  // auto-baud
    case 'U': {                                   // U<baud> start SCI sniff; U0 stop
      long baud = atol(s + 1);
      if (baud <= 0) {
        if (g_sciOn) { Serial1.end(); Serial2.end(); g_sciOn = false; }
        Serial.print("Usci off\r");
      } else {
        Serial1.begin(baud, SERIAL_8N1, SCI1_RX_PIN, -1);
        Serial2.begin(baud, SERIAL_8N1, SCI2_RX_PIN, -1);
        g_sciOn = true;
        Serial.printf("Usci on %ld 8N1 GPIO%d->@1 GPIO%d->@2\r", baud, SCI1_RX_PIN, SCI2_RX_PIN);
      }
      break;
    }
    default:  err(); break;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  delay(50);
  // Human banner (python-can flushes the input buffer on open, so this is harmless).
  Serial.print("\r\n# esp32_slcan ready: SLCAN @115200, TX=GPIO21 RX=GPIO22, default S4=125k\r\n");
}

void loop() {
  // drain serial commands
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      g_line[g_len] = 0;
      handleLine(g_line, g_len);
      g_len = 0;
    } else if (g_len < sizeof(g_line) - 1) {
      g_line[g_len++] = c;
    } else {
      g_len = 0; err();   // overrun
    }
  }
  // drain sniffed SCI bytes (independent of the CAN channel): @1 = GPIO34 (chip
  // SCI1TX / pin 31), @2 = GPIO35 (chip SCI2TX / pin 34), hex, CR-terminated
  if (g_sciOn) {
    if (Serial1.available()) {
      Serial.print("@1"); int g = 0;
      while (Serial1.available() && g++ < 64) { uint8_t b = Serial1.read(); Serial.write(nib(b >> 4)); Serial.write(nib(b & 0xF)); }
      Serial.write('\r');
    }
    if (Serial2.available()) {
      Serial.print("@2"); int g = 0;
      while (Serial2.available() && g++ < 64) { uint8_t b = Serial2.read(); Serial.write(nib(b >> 4)); Serial.write(nib(b & 0xF)); }
      Serial.write('\r');
    }
  }
  // drain received CAN frames
  if (g_open) {
    twai_message_t m;
    int guard = 0;
    while (twai_receive(&m, 0) == ESP_OK && guard++ < 32) {
      emitFrame(&m);
      digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    }
    // keepalive: a harmless low-priority frame every 80 ms so the bus never goes
    // quiet and the radio's CAN (which sleeps within ~1s of silence) stays awake,
    // independent of how fast the PC issues UDS requests
    if (g_keepalive && !g_listenOnly && (millis() - g_ka_last > 80)) {
      twai_message_t ka = {};
      ka.identifier = 0x7FF; ka.data_length_code = 1; ka.data[0] = 0x00;
      twai_transmit(&ka, 0);          // non-blocking; losing one is harmless
      g_ka_last = millis();
    }
    // surface bus faults into the SLCAN status byte
    twai_status_info_t st;
    if (twai_get_status_info(&st) == ESP_OK) {
      if (st.rx_missed_count || st.rx_overrun_count) g_status |= 0x08; // data overrun
      if (st.bus_error_count) g_status |= 0x20;                        // bus error
      if (st.state == TWAI_STATE_BUS_OFF) {
        g_status |= 0x80;
        twai_initiate_recovery();
      }
    }
  }
}
