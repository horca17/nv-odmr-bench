// Measurement engine for an NV-diamond ODMR bench (ESP32 + ADF4350).
// Derived from Uncut Gem by Quantum Village, licensed AGPL-3.0; modified.
// Serial commands: LIVE, PASO <n>, REG <R0..R5 hex>, MEDIR, RF <0|1>, RESET.

#include "sweep_config.h"
#include <SPI.h>
#include "adf4350.h"
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WiFi.h>

#define DAC_LASER_FIJO      75
#define DAC_LIVE_ALTO       95

#define N_LECTURAS           15
#define FRAC_RECORTE          0.15
#define DELAY_LECTURA_MS      5
#define DELAY_ASENTAM_MS     20

#define LASER_WARMUP_MS   10000

#define PIN_CE   17

#define PIN_LASER      27
#define PIN_DAC        25
#define ADC_PIN        34
#define COM_PIN        26

#define i2c_Address    0x3c
#define SCREEN_WIDTH   128
#define SCREEN_HEIGHT  64
#define OLED_RESET     -1

#define VENTANA_MS  80

ADF4350 PLL(COM_PIN, ADC_PIN);
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

bool rf_on = true;
byte R4_ON[4]  = {0x00, 0x86, 0x43, 0x24};
byte R4_OFF[4] = {0x00, 0x86, 0x43, 0x04};

void fase_laserWarmup();
void modoLive();
void medirRecortado(float &prom, float &mn, float &mx);
void comandoPaso(int n);
void comandoReg(String hex_r0, String hex_r1, String hex_r2, String hex_r3, String hex_r4, String hex_r5);
void comandoRF(int estado);
void comandoMedir();
bool hexABytes(String hex8, byte out[4]);

void setup() {
  Serial.begin(115200);
  delay(250);
  Serial.println("==============================================");
  Serial.println("  UNCUT GEM — MOTOR FASE 1 — modo interactivo");
  Serial.println("  rev 14 sept 2026 (+MEDIR) — Qubistry");
  Serial.println("==============================================");

  WiFi.mode(WIFI_OFF);
  btStop();

  pinMode(PIN_LASER, OUTPUT);
  digitalWrite(PIN_LASER, LOW);
  dacWrite(PIN_DAC, 255);

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  display.begin(SSD1306_SWITCHCAPVCC, i2c_Address);
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 20); display.println("UNCUT GEM FASE 1");
  display.setCursor(0, 35); display.println("Esperando Mac...");
  display.display();
  delay(1000);

  pinMode(PIN_CE, OUTPUT);
  digitalWrite(PIN_CE, HIGH);
  delay(10);

  PLL.init(2870, 25);
  PLL.setRfPower(2);
  delay(500);

  fase_laserWarmup();

  dacWrite(PIN_DAC, DAC_LASER_FIJO);
  digitalWrite(PIN_LASER, HIGH);

  Serial.println("\n[LISTO] Esperando comandos: LIVE | PASO <n> | REG <r0>..<r5> | MEDIR | RF <0|1> | RESET");
}

void loop() {
  if (!Serial.available()) return;

  String linea = Serial.readStringUntil('\n');
  linea.trim();
  if (linea.length() == 0) return;

  int primerEspacio = linea.indexOf(' ');
  String cmd = (primerEspacio < 0) ? linea : linea.substring(0, primerEspacio);
  String resto = (primerEspacio < 0) ? "" : linea.substring(primerEspacio + 1);
  cmd.toUpperCase();

  if (cmd == "LIVE") {
    modoLive();
    Serial.println("[LISTO] Esperando comandos.");

  } else if (cmd == "RESET") {
  resetADF();
  Serial.println("OK,reset");

  } else if (cmd == "PASO") {
    int n = resto.toInt();
    if (n < 0 || n > 127) {
      Serial.println("ERR,paso fuera de rango 0-127");
    } else {
      comandoPaso(n);
    }

  } else if (cmd == "MEDIR") {
    comandoMedir();

  } else if (cmd == "RF") {
    if (resto.length() == 0) {
      Serial.println("ERR,uso: RF 0|1");
    } else {
      comandoRF(resto.toInt());
    }

  } else if (cmd == "REG") {

    String tokens[6];
    int idx = 0;
    int start = 0;
    for (int i = 0; i <= resto.length() && idx < 6; i++) {
      if (i == resto.length() || resto[i] == ' ') {
        if (i > start) tokens[idx++] = resto.substring(start, i);
        start = i + 1;
      }
    }
    if (idx != 6) {
      Serial.println("ERR,se esperaban 6 registros hex (R0..R5)");
    } else {
      comandoReg(tokens[0], tokens[1], tokens[2], tokens[3], tokens[4], tokens[5]);
    }

  } else {
    Serial.println("ERR,comando no reconocido");
  }
}

void resetADF() {
  digitalWrite(PIN_CE, LOW);
  delay(10);
  digitalWrite(PIN_CE, HIGH);
  delay(10);
  PLL.init(2870, 25);
  delay(50);
  rf_on = true;
}

void fase_laserWarmup() {
  Serial.println("\n[WARMUP] Calentando laser 10s...");
  dacWrite(PIN_DAC, DAC_LASER_FIJO);
  digitalWrite(PIN_LASER, HIGH);
  unsigned long t0 = millis();
  while (millis() - t0 < LASER_WARMUP_MS) {
    display.clearDisplay();
    display.setCursor(0, 20); display.println("LASER WARMUP");
    display.setCursor(0, 35); display.printf("t: %lu/%d ms", millis() - t0, LASER_WARMUP_MS);
    display.display();
    delay(200);
  }
  digitalWrite(PIN_LASER, LOW);
  dacWrite(PIN_DAC, 255);
  Serial.println("[WARMUP] OK");
}

#define VENTANA_MS  80

void medirRecortado(float &prom, float &mn, float &mx) {
  unsigned long t0 = millis();
  double suma = 0; long n = 0;
  int vmin = 4095, vmax = 0;
  while (millis() - t0 < VENTANA_MS) {
    int v = analogRead(ADC_PIN);
    suma += v; n++;
    if (v < vmin) vmin = v;
    if (v > vmax) vmax = v;
  }
  prom = (float)(suma / n);
  mn = vmin; mx = vmax;
}

void comandoPaso(int n) {
  PLL.send_sweep_step(n);
  if (!rf_on) PLL.writeRegisterRaw(R4_OFF);
  delay(DELAY_ASENTAM_MS);
  float prom, mn, mx;
  medirRecortado(prom, mn, mx);
  Serial.printf("OK,%.2f,%.0f,%.0f\n", prom, mn, mx);
}

void comandoMedir() {
  delay(DELAY_ASENTAM_MS);
  float prom, mn, mx;
  medirRecortado(prom, mn, mx);
  Serial.printf("OK,%.2f,%.0f,%.0f\n", prom, mn, mx);
}

void comandoRF(int estado) {
  rf_on = (estado != 0);
  PLL.writeRegisterRaw(rf_on ? R4_ON : R4_OFF);
  delay(DELAY_ASENTAM_MS);
  Serial.printf("OK,RF=%s\n", rf_on ? "ON" : "OFF");
}

void comandoReg(String hex_r0, String hex_r1, String hex_r2, String hex_r3, String hex_r4, String hex_r5) {
  byte r0[4], r1[4], r2[4], r3[4], r4[4], r5[4];
  bool ok = hexABytes(hex_r0, r0) && hexABytes(hex_r1, r1) && hexABytes(hex_r2, r2) &&
            hexABytes(hex_r3, r3) && hexABytes(hex_r4, r4) && hexABytes(hex_r5, r5);
  if (!ok) {
    Serial.println("ERR,formato hex invalido (se esperan 8 caracteres por registro)");
    return;
  }

  PLL.writeRegisterRaw(r5);
  PLL.writeRegisterRaw(r4);
  PLL.writeRegisterRaw(r3);
  PLL.writeRegisterRaw(r2);
  PLL.writeRegisterRaw(r1);
  PLL.writeRegisterRaw(r0);

  delay(DELAY_ASENTAM_MS);
  float prom, mn, mx;
  medirRecortado(prom, mn, mx);
  Serial.printf("OK,%.2f,%.0f,%.0f\n", prom, mn, mx);
}

bool hexABytes(String hex8, byte out[4]) {
  if (hex8.length() != 8) return false;
  for (int i = 0; i < 4; i++) {
    String par = hex8.substring(i*2, i*2+2);
    char* endptr;
    long val = strtol(par.c_str(), &endptr, 16);
    if (*endptr != '\0') return false;
    out[i] = (byte)val;
  }
  return true;
}

void modoLive() {
  Serial.println("[LIVE] Alternando DAC 75/80 — mova el laser buscando el MAXIMO delta.");
  Serial.println("[LIVE] Escribi 'si' + Enter cuando encuentres el punto optimo.");

  while (true) {
    if (Serial.available()) {
      String resp = Serial.readStringUntil('\n');
      resp.trim(); resp.toLowerCase();
      if (resp == "si" || resp == "s") {
        Serial.println("[LIVE] Confirmado.");
        break;
      }
    }
    float mn, mx, tia75, tia80;
    dacWrite(PIN_DAC, DAC_LASER_FIJO);
    delay(DELAY_ASENTAM_MS);
    medirRecortado(tia75, mn, mx);

    dacWrite(PIN_DAC, DAC_LIVE_ALTO);
    delay(DELAY_ASENTAM_MS);
    medirRecortado(tia80, mn, mx);

    float delta_live = tia75 - tia80;
    Serial.printf("TIA75=%.1f  TIA80=%.1f  delta=%.1f\n", tia75, tia80, delta_live);

    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 0);  display.println("MODO LIVE");
    display.drawFastHLine(0, 9, 128, SSD1306_WHITE);
    display.setCursor(0, 16); display.printf("DAC75: %.0f", tia75);
    display.setCursor(0, 28); display.printf("DAC80: %.0f", tia80);
    display.setCursor(0, 40); display.printf("DELTA: %.0f", delta_live);
    display.setCursor(0, 54); display.println("'si' Serial=terminar");
    display.display();
  }

  dacWrite(PIN_DAC, DAC_LASER_FIJO);
  digitalWrite(PIN_LASER, HIGH);
}
