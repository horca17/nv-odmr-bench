// uncut-gem-v5.1 — magnetometro NV: motor de medicion (ESP32) + modo AUTO
// Basado en Uncut Gem (Quantum Village), GNU AGPL v3.
//
// Lock-in por modulacion de frecuencia (+-3 MHz, 37 Hz) sobre una linea ODMR y lazo cerrado
// con la corriente de una bobina (DAC GPIO25). Con parametros guardados, al encender verifica
// la linea y mide solo; la pendiente se vuelve a medir cada 3 min.
//   B = -K * (D - D0) - X / (pendiente * gamma)
//
// Comandos: SET REG MEDIR RF RESET FM LOCKIN MOTOR ATEN SYNC BOBINA TEMP INFO (frenan el AUTO)
//   GUARDAR <f_busca> <d0> <k> [gan]   AUTO   STOP   ESTADO   PANTALLA <0|1>   FUENTE [BC337|OPAMP]
// Salida en modo AUTO: DATO,t_s,campo_uT,D,X,temp_C,luz,pendiente,estado

#include <SPI.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Preferences.h>

#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3) && SOC_ADC_DMA_SUPPORTED
  #define HAY_DMA 1
  #include "esp_adc/adc_continuous.h"
#else
  #define HAY_DMA 0
#endif

#define VERSION "v5.1"

#define PIN_ADF_LE   26
#define PIN_ADF_CE   17
#define PIN_ADC      34
#define PIN_BOBINA   25
#define PIN_TEMP     33
#define PIN_SYNC     32

#define OLED_ADDR    0x3C
Adafruit_SSD1306 display(128, 64, &Wire, -1);

#define ASENT_MS     20
#define VENTANA_MS   80
#define LOCKIN_M     16
#define SPI_HZ       100000

SPIClass *spiADF = nullptr;

byte reg[6][4] = {
  {0x00, 0x72, 0x80, 0x78},
  {0x00, 0x00, 0x80, 0xC9},
  {0x38, 0x00, 0xBE, 0x42},
  {0x00, 0x04, 0x00, 0x03},
  {0x00, 0x86, 0x43, 0x1C},
  {0x00, 0x58, 0x00, 0x05}
};
byte r4_on[4], r4_off[4];
bool rf_on = false;

byte r0_fm_lo[4] = {0, 0, 0, 0};
byte r0_fm_hi[4] = {0, 0, 0, 0};
bool fm_ok = false;
int  fm_descarte = 0;

void adfEscribir(const byte d[4]) {
  spiADF->beginTransaction(SPISettings(SPI_HZ, MSBFIRST, SPI_MODE0));
  digitalWrite(PIN_ADF_LE, LOW);
  for (int i = 0; i < 4; i++) spiADF->transfer(d[i]);
  digitalWrite(PIN_ADF_LE, HIGH);
  spiADF->endTransaction();
}

void actualizarR4() {
  for (int i = 0; i < 4; i++) { r4_on[i] = reg[4][i]; r4_off[i] = reg[4][i]; }
  r4_on[3]  |=  0x20;
  r4_off[3] &= ~0x20;
}

void adfEscribirTodos() {
  for (int i = 5; i >= 0; i--) adfEscribir(reg[i]);
  rf_on = (reg[4][3] & 0x20) != 0;
}

int      motor   = 0;
uint32_t dma_fs  = 100000;
int      aten_db = 11;
bool     sync_on = false;

bool     dac_on  = false;
uint32_t bobina_d = 0;

OneWire           unoWire(PIN_TEMP);
DallasTemperature sensorT(&unoWire);
bool          temp_ok   = false;
float         temp_c    = NAN;
unsigned long temp_ms   = 0;
unsigned long temp_pide = 0;
#define TEMP_CONV_MS 800

void servicioTemp();
void medirVentana(float &prom, float &mn, float &mx);
void responderMedicion();
bool cargarRegs(String t[6]);
bool hexABytes(const String &hex8, byte out[4]);
int  partirTokens(const String &s, String t[], int maxTok);
adc_attenuation_t atenEnum(int db);
void comandoBobina(String arg);
long bobinaAplicar(long d);
void comandoInfo();
void comandoGuardar(const String &resto);
void comandoLockin(float fmod, int ciclos, int modo, int asent_ms);
struct ResLockin { bool ok; double media, x, y; long n; char err[64]; };
ResLockin RL;
void lockinAnalogRead(float fmod, int ciclos, int modo);
#if HAY_DMA
void lockinDMA(float fmod, int ciclos, int modo);
#endif
bool medirLockin(float fmod, int ciclos, int modo, int asent_ms);

Preferences prefs;
bool  hay_conf = false;
float P_FBUSCA = 2833.5;
long  P_D0     = 3228;
float P_KCAL   = 0.0586;
float P_GAN    = 0.5;

#define GAMMA        0.028
#define SEMI         8.0
#define PASO_PRUEBA  160

#define D_MIN_BC337  1600
#define D_MAX_BC337  4095
#define D_MIN_OPAMP  0
#define D_MAX_OPAMP  3400
bool fuente_opamp = true;
long D_MIN = D_MIN_OPAMP, D_MAX = D_MAX_OPAMP;
void aplicarFuente(bool op) { fuente_opamp = op; D_MIN = op ? D_MIN_OPAMP : D_MIN_BC337; D_MAX = op ? D_MAX_OPAMP : D_MAX_BC337; }
#define CADA_PEND_MS 180000UL
#define TOL_PEND     0.5
#define DELTA_FM     3.0
#define FMOD_HZ      37.0
#define CICLOS       37
#define REINTENTO_MS 30000UL
#define SAT_MAX_MS   30000UL
#define PFD_MHZ      12.5
#define MODU         25

const byte REG_TRABAJO[5][4] = {
  {0x00, 0x00, 0x80, 0xC9}, {0x38, 0x00, 0xBE, 0x42}, {0x00, 0x04, 0x00, 0x03},
  {0x00, 0x86, 0x43, 0x3C}, {0x00, 0x58, 0x00, 0x05}
};

enum EstadoAuto { A_OFF, A_VERIF, A_ESPERA, A_MIDE };
EstadoAuto est = A_OFF;
bool   auto_on   = false;
bool   pantalla_on = true;
String pendiente = "";
String aviso     = "";
unsigned long t_reintento = 0, t_pend = 0, t_med0 = 0, sat_desde = 0, t_pant = 0;
double F0 = 0, linea_f = 0, pend0 = 0, pend = 0, dXdD = 0, Kc = 0, k_rap = 0;
double d_cont = 0, campo = 0, x_ult = 0, luz_ult = 0;
long   d0r = 0, dreal = 0, vueltas = 0;
bool   aviso_k = false, sat = false;
#define NHIST 128
float  hist[NHIST]; int nhist = 0;

void r0bytes(double f, byte b[4]) {
  long n = lround(f / PFD_MHZ * MODU);
  uint32_t r0 = ((uint32_t)(n / MODU) << 15) | ((uint32_t)(n % MODU) << 3);
  b[0] = r0 >> 24; b[1] = r0 >> 16; b[2] = r0 >> 8; b[3] = r0;
}
void setFrec(double f) {
  r0bytes(f, reg[0]);
  for (int i = 0; i < 5; i++) memcpy(reg[i + 1], REG_TRABAJO[i], 4);
  actualizarR4();
  adfEscribirTodos();
}

bool xfm(double f, int ciclos, double &luz, double &x) {
  setFrec(f);
  r0bytes(f - DELTA_FM, r0_fm_lo); r0bytes(f + DELTA_FM, r0_fm_hi);
  fm_ok = true; fm_descarte = 1;
  if (!medirLockin(FMOD_HZ, ciclos, 4, ASENT_MS)) return false;
  luz = RL.media; x = RL.x;
  return true;
}
long poner(long d) {
  long r = bobinaAplicar(d);
  delay(300);
  return r;
}

void pantallaTexto(const char *a, const char *b, const char *c) {
  if (!pantalla_on) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);  display.print("UNCUT GEM " VERSION);
  display.setCursor(0, 20); display.print(a);
  display.setCursor(0, 34); display.print(b);
  display.setCursor(0, 48); display.print(c);
  display.display();
}
void pantallaMedicion() {
  if (!pantalla_on) return;
  char s[32];
  display.clearDisplay();
  display.setTextSize(2); display.setCursor(0, 0);
  if (sat) {
    double lim = (d_cont >= D_MAX) ? -Kc * (D_MAX - d0r) : Kc * (d0r - D_MIN);
    display.print("SAT");
    display.setTextSize(1); display.setCursor(44, 4);
    snprintf(s, sizeof(s), "%s%+.0f uT", lim > 0 ? ">" : "<", lim);
    display.print(s);
    s[0] = 0;
  } else {
    snprintf(s, sizeof(s), "%+.1f uT", campo);
  }
  display.print(s);

  int n = nhist < NHIST ? nhist : NHIST;
  if (n > 10) {
    float m[NHIST]; int k = 0;
    for (int i = 9; i < n; i++) {
      float a = 0;
      for (int j = i - 9; j <= i; j++) a += hist[(nhist - n + j) % NHIST];
      m[k++] = a / 10;
    }
    float lo = m[0], hi = m[0];
    for (int i = 1; i < k; i++) { if (m[i] < lo) lo = m[i]; if (m[i] > hi) hi = m[i]; }
    if (hi - lo < 2) { float c = (hi + lo) / 2; lo = c - 1; hi = c + 1; }
    for (int i = 1; i < k; i++) {
      int x0 = (i - 1) * 127 / (k - 1), x1 = i * 127 / (k - 1);
      int y0 = 46 - (int)((m[i - 1] - lo) / (hi - lo) * 26);
      int y1 = 46 - (int)((m[i] - lo) / (hi - lo) * 26);
      display.drawLine(x0, y0, x1, y1, SSD1306_WHITE);
    }
  }
  display.setTextSize(1); display.setCursor(0, 56);
  const char *e = sat ? "SAT" : aviso_k ? "K?" : !temp_ok ? "T?" : "OK";
  if (temp_ok) snprintf(s, sizeof(s), "T%.1f D%ld p%.2f %s", temp_c, dreal, pend, e);
  else         snprintf(s, sizeof(s), "D%ld p%.2f %s", dreal, pend, e);
  display.print(s);
  display.display();
}

void detenerAuto(const char *porque) {
  if (!auto_on) return;
  auto_on = false; est = A_OFF;
  Serial.printf("[AUTO] detenido (%s): control de la Mac\n", porque);
  pantallaTexto("MODO MAC", "(comandos por USB)", "");
}
const char *nombreEstado() {
  switch (est) { case A_VERIF: return "VERIF"; case A_ESPERA: return "ESPERA"; case A_MIDE: return "MIDE"; default: return "MAC"; }
}
void comandoEstado() {
  Serial.printf("OK,ESTADO,modo=%s,campo=%.3f,D=%ld,pend=%.4f,F0=%.1f,temp=%.3f,sat=%d,aviso=%s,conf=%d,fuente=%s\n",
                nombreEstado(), campo, dreal, pend, F0, isnan(temp_c) ? 0.0 : temp_c, sat ? 1 : 0,
                aviso_k ? "K?" : aviso.c_str(), hay_conf ? 1 : 0, fuente_opamp ? "OPAMP" : "BC337");
}
void comandoPantalla(const String &resto) {
  if (resto != "0" && resto != "1") { Serial.println("ERR,uso: PANTALLA 0|1"); return; }
  pantalla_on = (resto == "1");
  if (!pantalla_on) { display.clearDisplay(); display.display(); }
  Serial.printf("OK,PANTALLA=%d\n", pantalla_on ? 1 : 0);
}

bool revisarSerie() {
  while (Serial.available()) {
    String l = Serial.readStringUntil('\n'); l.trim();
    if (l.length() == 0) continue;
    int e = l.indexOf(' ');
    String c = (e < 0) ? l : l.substring(0, e); c.toUpperCase();
    String r = (e < 0) ? "" : l.substring(e + 1); r.trim();
    if (c == "ESTADO")   { comandoEstado(); continue; }
    if (c == "PANTALLA") { comandoPantalla(r); continue; }
    if (c == "GUARDAR")  { comandoGuardar(r); continue; }
    pendiente = l;
    detenerAuto(c.c_str());
    return true;
  }
  return false;
}

int verificar() {
  double luz, x;
  motor = 1; dma_fs = 200000;
  aviso = ""; aviso_k = false;
  pantallaTexto("VERIFICANDO", "1/3 buscando loma", "");
  Serial.printf("[AUTO] verificando: F_BUSCA %.1f  D0 %ld  K_CAL %.4f\n", P_FBUSCA, P_D0, P_KCAL);
  d0r = poner(P_D0); delay(2000);

  const int NB = (int)(2 * SEMI / 0.5) + 1;
  double fb[40], xb[40];
  for (int j = 0; j < NB; j++) {
    fb[j] = P_FBUSCA - SEMI + 0.5 * j;
    if (!xfm(fb[j], 18, luz, xb[j])) { aviso = "ERR LOCKIN"; return 0; }
    if (revisarSerie()) return -1;
  }
  bool hay = false; double mejor = 0;
  for (int j = 0; j < NB - 1; j++) {
    if (xb[j] > 0 && xb[j + 1] <= 0) {
      double c = fb[j] + 0.5 * xb[j] / (xb[j] - xb[j + 1]);
      if (!hay || fabs(c - P_FBUSCA) < fabs(mejor - P_FBUSCA)) { mejor = c; hay = true; }
    }
  }
  if (!hay) { aviso = "SIN LOMA"; return 0; }
  linea_f = mejor; F0 = round(linea_f * 2) / 2;

  pantallaTexto("VERIFICANDO", "2/3 pendiente", "");
  double s = 0;
  for (int i = 0; i < 4; i++) {
    double xa, xb2;
    if (!xfm(F0 + 0.5, CICLOS, luz, xa) || !xfm(F0 - 0.5, CICLOS, luz, xb2)) { aviso = "ERR LOCKIN"; return 0; }
    s += xa - xb2;
    if (revisarSerie()) return -1;
  }
  pend0 = s / 4;
  if (!(pend0 < -0.3 && pend0 > -2.0)) { aviso = "PENDIENTE " + String(pend0, 2); return 0; }

  pantallaTexto("VERIFICANDO", "3/3 K rapido", "");
  long dr[2]; double r[2];
  for (int k = 0; k < 2; k++) {
    dr[k] = poner(k == 0 ? P_D0 + PASO_PRUEBA : P_D0 - PASO_PRUEBA);
    double a = 0;
    for (int i = 0; i < 8; i++) {
      if (!xfm(F0, CICLOS, luz, x)) { aviso = "ERR LOCKIN"; return 0; }
      a += x;
      if (revisarSerie()) return -1;
    }
    r[k] = a / 8;
  }
  d0r = poner(P_D0);
  k_rap = -(r[0] - r[1]) / (double)(dr[0] - dr[1]) / pend0 / GAMMA;
  aviso_k = !(k_rap > 0 && k_rap / P_KCAL > 0.5 && k_rap / P_KCAL < 2);
  Serial.printf("[AUTO] loma %.2f MHz  F0 %.1f  pendiente %+.3f  K rapido %+.4f (calibrado %.4f)%s%s\n",
                linea_f, F0, pend0, k_rap, P_KCAL, aviso_k ? "  ** AVISO K **" : "", temp_ok ? "" : "  ** sin temperatura **");

  Kc = P_KCAL; pend = pend0; dXdD = -Kc * pend * GAMMA;
  d_cont = d0r; dreal = d0r; vueltas = 0; nhist = 0; sat = false; sat_desde = 0;
  t_pend = millis() - CADA_PEND_MS;
  t_med0 = millis();
  Serial.println("[AUTO] midiendo. DATO,t_s,campo_uT,D,X,temp_C,luz,pendiente,estado");
  return 1;
}

void vueltaLazo() {
  double luz, x;
  if (millis() - t_pend >= CADA_PEND_MS) {
    double s = 0; bool ok = true;
    for (int i = 0; i < 2 && ok; i++) {
      double xa, xb;
      ok = xfm(F0 + 0.5, CICLOS, luz, xa) && xfm(F0 - 0.5, CICLOS, luz, xb);
      s += xa - xb;
      if (revisarSerie()) return;
    }
    double pv = s / 2;
    bool acepta = ok && pv < 0 && pv / pend > (1 - TOL_PEND) && pv / pend < (1 + TOL_PEND);
    if (acepta) { pend = pv; dXdD = -Kc * pend * GAMMA; }
    Serial.printf("[AUTO] pendiente medida %+.3f %s\n", pv, acepta ? "(en uso)" : "(descartada)");
    t_pend = millis();
  }
  if (!xfm(F0, CICLOS, luz, x)) { Serial.printf("[AUTO] lectura descartada: %s\n", RL.err); return; }
  if (revisarSerie()) return;
  servicioTemp();
  double b_res = -x / pend / GAMMA;
  campo = -Kc * (dreal - d0r) + b_res;
  x_ult = x; luz_ult = luz;
  d_cont = d_cont - P_GAN * x / dXdD;
  if (d_cont < D_MIN) d_cont = D_MIN;
  if (d_cont > D_MAX) d_cont = D_MAX;
  sat = (d_cont <= D_MIN || d_cont >= D_MAX);
  Serial.printf("DATO,%.1f,%.3f,%ld,%.4f,%.3f,%.1f,%.4f,%s\n", (millis() - t_med0) / 1000.0, campo, dreal, x,
                isnan(temp_c) ? 0.0 : temp_c, luz, pend, sat ? "SAT" : aviso_k ? "K?" : "OK");
  dreal = poner(lround(d_cont));
  hist[nhist % NHIST] = campo; nhist++; vueltas++;
  if (sat) {
    if (sat_desde == 0) sat_desde = millis();
    else if (millis() - sat_desde > SAT_MAX_MS) {
      Serial.println("[AUTO] saturado mas de 30 s: vuelve a verificar");
      est = A_VERIF; return;
    }
  } else sat_desde = 0;
  if (vueltas % 3 == 0) pantallaMedicion();
}

void pasoAuto() {
  if (est == A_VERIF) {
    int r = verificar();
    if (r == 1) { est = A_MIDE; pantallaTexto("MIDIENDO", "", ""); }
    else if (r == 0) {
      est = A_ESPERA; t_reintento = millis() + REINTENTO_MS;
      Serial.printf("[AUTO] verificacion fallida: %s. Reintenta en 30 s\n", aviso.c_str());
    }
  } else if (est == A_ESPERA) {
    if ((long)(millis() - t_reintento) >= 0) { est = A_VERIF; return; }
    if (millis() - t_pant > 1000) {
      char b[40]; snprintf(b, sizeof(b), "reintenta en %lu s", (t_reintento - millis()) / 1000 + 1);
      pantallaTexto(aviso.c_str(), b, "");
      t_pant = millis();
    }
    revisarSerie();
    delay(20);
  } else if (est == A_MIDE) {
    vueltaLazo();
  }
}

void comandoGuardar(const String &resto) {
  String t[4];
  int n = partirTokens(resto, t, 4);
  float f = (n >= 1) ? t[0].toFloat() : 0, k = (n >= 3) ? t[2].toFloat() : 0, g = (n >= 4) ? t[3].toFloat() : 0.5;
  long d = (n >= 2) ? t[1].toInt() : -1;
  if (n < 3 || f < 2700 || f > 3000 || d < 0 || d > 4095 || k < 0.01 || k > 0.2 || g < 0.05 || g > 1.0) {
    Serial.println("ERR,uso: GUARDAR <f_busca 2700-3000> <d0 0-4095> <k_cal 0.01-0.2> [gan 0.05-1]");
    return;
  }
  P_FBUSCA = f; P_D0 = d; P_KCAL = k; P_GAN = g; hay_conf = true;
  prefs.putFloat("fbusca", f); prefs.putLong("d0", d); prefs.putFloat("kcal", k); prefs.putFloat("gan", g);
  prefs.putBool("conf", true);
  Serial.printf("OK,GUARDAR,f_busca=%.1f,d0=%ld,k_cal=%.4f,gan=%.2f\n", f, d, k, g);
}
void comandoAuto() {
  if (!hay_conf) { Serial.println("ERR,sin configuracion: usar GUARDAR <f_busca> <d0> <k_cal>"); return; }
  auto_on = true; est = A_VERIF;
  Serial.println("OK,AUTO");
}

void setup() {
  Serial.begin(115200);
  delay(250);
  Serial.println("==============================================");
  Serial.println("  UNCUT GEM — motor de medicion " VERSION " (22 oct 2026)");
  Serial.println("==============================================");

  btStop();

  pinMode(PIN_BOBINA, OUTPUT);
  digitalWrite(PIN_BOBINA, LOW);

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
  Wire.setClock(400000);
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 20); display.println("UNCUT GEM " VERSION);
  display.setCursor(0, 35); display.println("Esperando comandos");
  display.display();

  unoWire.begin(PIN_TEMP);
  delay(5);
  int presencia = unoWire.reset();
  sensorT.begin();
  temp_ok = (sensorT.getDeviceCount() > 0);
  if (temp_ok) {
    sensorT.setResolution(12);
    sensorT.setWaitForConversion(false);
    sensorT.requestTemperatures();
    temp_pide = millis();
  }
  Serial.printf("[TEMP] presencia %d, DS18B20 en GPIO33: %s\n", presencia, temp_ok ? "OK" : "NO ENCONTRADO");

  pinMode(PIN_ADF_LE, OUTPUT);
  digitalWrite(PIN_ADF_LE, HIGH);
  spiADF = new SPIClass(VSPI);
  spiADF->begin(SCK, MISO, MOSI, SS);
  pinMode(PIN_ADF_CE, OUTPUT);
  digitalWrite(PIN_ADF_CE, HIGH);
  delay(10);
  actualizarR4();
  adfEscribirTodos();
  delay(50);

  prefs.begin("uncutgem", false);
  hay_conf = prefs.getBool("conf", false);
  aplicarFuente(prefs.getBool("opamp", true));
  if (hay_conf) {
    P_FBUSCA = prefs.getFloat("fbusca", 2833.5); P_D0 = prefs.getLong("d0", 3228);
    P_KCAL = prefs.getFloat("kcal", 0.0586);     P_GAN = prefs.getFloat("gan", 0.5);
  }
  Serial.println("[LISTO] " VERSION " — SET REG MEDIR RF RESET FM LOCKIN MOTOR ATEN SYNC BOBINA TEMP INFO GUARDAR AUTO ESTADO PANTALLA STOP FUENTE");
  Serial.printf("[FUENTE] %s: D entre %ld y %ld\n", fuente_opamp ? "OPAMP (LM324)" : "BC337", D_MIN, D_MAX);
  if (hay_conf) {
    Serial.printf("[AUTO] parametros: F_BUSCA %.1f  D0 %ld  K_CAL %.4f  GAN %.2f -> verifica y mide solo\n", P_FBUSCA, P_D0, P_KCAL, P_GAN);
    auto_on = true; est = A_VERIF;
  } else {
    Serial.println("[AUTO] sin parametros guardados (usar GUARDAR): espera comandos de la Mac");
    pantallaTexto("SIN CONFIG", "esperando la Mac", "");
  }
}

void loop() {
  servicioTemp();
  if (pendiente.length() == 0 && !Serial.available()) {
    if (auto_on) pasoAuto();
    return;
  }

  String linea;
  if (pendiente.length() > 0) { linea = pendiente; pendiente = ""; }
  else linea = Serial.readStringUntil('\n');
  linea.trim();
  if (linea.length() == 0) return;

  int esp = linea.indexOf(' ');
  String cmd   = (esp < 0) ? linea : linea.substring(0, esp);
  String resto = (esp < 0) ? "" : linea.substring(esp + 1);
  resto.trim();
  cmd.toUpperCase();

  if (cmd == "ESTADO")   { comandoEstado(); return; }
  if (cmd == "PANTALLA") { comandoPantalla(resto); return; }
  if (cmd == "GUARDAR")  { comandoGuardar(resto); return; }
  if (cmd == "AUTO")     { comandoAuto(); return; }
  if (cmd == "STOP")     {
    if (auto_on) detenerAuto("STOP"); else pantallaTexto("MODO MAC", "(comandos por USB)", "");
    Serial.println("OK,STOP"); return;
  }
  if (cmd == "FUENTE")   {
    resto.toUpperCase();
    if (resto == "BC337" || resto == "OPAMP") {
      detenerAuto("FUENTE");
      aplicarFuente(resto == "OPAMP"); prefs.putBool("opamp", fuente_opamp);
      if (dac_on && (long)bobina_d > D_MAX) bobinaAplicar(D_MAX);
    } else if (resto.length() > 0) { Serial.println("ERR,uso: FUENTE [BC337|OPAMP]"); return; }
    Serial.printf("OK,FUENTE=%s,d_min=%ld,d_max=%ld\n", fuente_opamp ? "OPAMP" : "BC337", D_MIN, D_MAX);
    return;
  }
  detenerAuto(cmd.c_str());

  if (cmd == "SET") {
    String t[6];
    if (partirTokens(resto, t, 6) != 6) Serial.println("ERR,se esperaban 6 registros hex (R0..R5)");
    else if (cargarRegs(t)) Serial.println("OK,SET");

  } else if (cmd == "REG") {
    String t[6];
    if (partirTokens(resto, t, 6) != 6) Serial.println("ERR,se esperaban 6 registros hex (R0..R5)");
    else if (cargarRegs(t)) responderMedicion();

  } else if (cmd == "MEDIR") {
    responderMedicion();

  } else if (cmd == "RF") {
    if (resto != "0" && resto != "1") { Serial.println("ERR,uso: RF 0|1"); return; }
    rf_on = (resto == "1");
    adfEscribir(rf_on ? r4_on : r4_off);
    delay(ASENT_MS);
    Serial.printf("OK,RF=%s\n", rf_on ? "ON" : "OFF");

  } else if (cmd == "RESET") {
    digitalWrite(PIN_ADF_CE, LOW);  delay(10);
    digitalWrite(PIN_ADF_CE, HIGH); delay(10);
    adfEscribirTodos();
    delay(50);
    Serial.println("OK,reset");

  } else if (cmd == "FM") {
    String t[3];
    int n = partirTokens(resto, t, 3);
    if (n < 2 || !hexABytes(t[0], r0_fm_lo) || !hexABytes(t[1], r0_fm_hi)) {
      fm_ok = false;
      Serial.println("ERR,uso: FM <R0bajo hex8> <R0alto hex8> [0|1]");
    } else {
      fm_descarte = (n == 3) ? t[2].toInt() : 0;
      fm_ok = true;
      Serial.println("OK,FM");
    }

  } else if (cmd == "LOCKIN") {
    String t[4];
    int n = partirTokens(resto, t, 4);
    float fmod  = (n >= 1) ? t[0].toFloat() : 37;
    int  ciclos = (n >= 2) ? t[1].toInt()   : 37;
    int  modo   = (n >= 3) ? t[2].toInt()   : 4;
    int  asent  = (n >= 4) ? t[3].toInt()   : ASENT_MS;
    if (fmod < 5 || fmod > 1000 || ciclos < 1 || ciclos > 5000 || asent < 0 || asent > 1000)
      Serial.println("ERR,uso: LOCKIN <5-1000 Hz> <1-5000 ciclos> <modo 0|2|4> [asent 0-1000 ms]");
    else if (modo != 0 && modo != 2 && modo != 4)
      Serial.println("ERR,modo no disponible en v5 (solo 0, 2, 4)");
    else if (modo == 4 && !fm_ok)
      Serial.println("ERR,modo 4 requiere un FM valido antes");
    else
      comandoLockin(fmod, ciclos, modo, asent);

  } else if (cmd == "MOTOR") {
    String t[2];
    int n = partirTokens(resto, t, 2);
    int m = (n >= 1) ? t[0].toInt() : -1;
    long fs = (n >= 2) ? t[1].toInt() : (long)dma_fs;
    if (m != 0 && m != 1)                     Serial.println("ERR,uso: MOTOR 0|1 [fs 20000-1000000]");
    else if (m == 1 && !HAY_DMA)              Serial.println("ERR,este core no tiene ADC continuo (requiere core 3.x)");
    else if (m == 1 && (fs < 20000 || fs > 1000000)) Serial.println("ERR,fs fuera de rango 20000-1000000");
    else {
      motor = m;
      if (m == 1) dma_fs = (uint32_t)fs;
      Serial.printf("OK,MOTOR=%d,fs=%lu\n", motor, (unsigned long)dma_fs);
    }

  } else if (cmd == "ATEN") {
    float a = resto.toFloat();
    int db = -1;
    if (resto == "0")               db = 0;
    else if (a > 2.0f && a < 3.0f)  db = 2;
    else if (a > 5.5f && a < 6.5f)  db = 6;
    else if (a > 10.5f && a < 12.5f) db = 11;
    if (db < 0) Serial.println("ERR,uso: ATEN 0|2.5|6|11");
    else {
      aten_db = db;
      analogSetPinAttenuation(PIN_ADC, atenEnum(aten_db));
      Serial.printf("OK,ATEN=%s\n", db == 2 ? "2.5" : String(db).c_str());
    }

  } else if (cmd == "SYNC") {
    if (resto != "0" && resto != "1") { Serial.println("ERR,uso: SYNC 0|1"); return; }
    sync_on = (resto == "1");
    if (sync_on) { pinMode(PIN_SYNC, OUTPUT); digitalWrite(PIN_SYNC, LOW); }
    else         { pinMode(PIN_SYNC, INPUT); }
    Serial.printf("OK,SYNC=%d\n", sync_on ? 1 : 0);

  } else if (cmd == "BOBINA") {
    comandoBobina(resto);

  } else if (cmd == "TEMP") {
    if (!temp_ok || isnan(temp_c)) Serial.println("ERR,TEMP sin sensor o sin lectura todavia");
    else Serial.printf("OK,TEMP=%.4f,edad_ms=%lu\n", temp_c, millis() - temp_ms);

  } else if (cmd == "INFO") {
    comandoInfo();

  } else {
    Serial.println("ERR,comando no reconocido");
  }
}

int partirTokens(const String &s, String t[], int maxTok) {
  int n = 0, ini = 0;
  for (int i = 0; i <= (int)s.length() && n < maxTok; i++) {
    if (i == (int)s.length() || s[i] == ' ') {
      if (i > ini) t[n++] = s.substring(ini, i);
      ini = i + 1;
    }
  }
  return n;
}

bool hexABytes(const String &hex8, byte out[4]) {
  if (hex8.length() != 8) return false;
  for (int i = 0; i < 4; i++) {
    String par = hex8.substring(i * 2, i * 2 + 2);
    char *fin;
    long v = strtol(par.c_str(), &fin, 16);
    if (*fin != '\0') return false;
    out[i] = (byte)v;
  }
  return true;
}

adc_attenuation_t atenEnum(int db) {
  switch (db) {
    case 0:  return ADC_0db;
    case 2:  return ADC_2_5db;
    case 6:  return ADC_6db;
    default: return ADC_11db;
  }
}

bool cargarRegs(String t[6]) {
  byte r[6][4];
  for (int i = 0; i < 6; i++) {
    if (!hexABytes(t[i], r[i])) {
      Serial.println("ERR,formato hex invalido (se esperan 8 caracteres por registro)");
      return false;
    }
  }
  memcpy(reg, r, sizeof(reg));
  actualizarR4();
  adfEscribirTodos();
  return true;
}

void medirVentana(float &prom, float &mn, float &mx) {
  unsigned long t0 = millis();
  double suma = 0; long n = 0;
  int vmin = 4095, vmax = 0;
  while (millis() - t0 < VENTANA_MS) {
    int v = analogRead(PIN_ADC);
    suma += v; n++;
    if (v < vmin) vmin = v;
    if (v > vmax) vmax = v;
  }
  prom = (n > 0) ? (float)(suma / n) : 0.0f;
  mn = vmin; mx = vmax;
}

void responderMedicion() {
  delay(ASENT_MS);
  float prom, mn, mx;
  medirVentana(prom, mn, mx);
  Serial.printf("OK,%.2f,%.0f,%.0f\n", prom, mn, mx);
}

void servicioTemp() {
  if (!temp_ok) return;
  if (millis() - temp_pide < TEMP_CONV_MS) return;
  float t = sensorT.getTempCByIndex(0);
  if (t != DEVICE_DISCONNECTED_C && t > -55.0f && t < 125.0f) {
    temp_c = t;
    temp_ms = millis();
  }
  sensorT.requestTemperatures();
  temp_pide = millis();
}

void comandoBobina(String arg) {
  arg.trim(); arg.toUpperCase();
  if (arg.length() == 0) {
    if (dac_on) Serial.printf("OK,BOBINA=%lu\n", (unsigned long)bobina_d);
    else        Serial.println("OK,BOBINA=OFF");
    return;
  }
  if (arg == "OFF") {
    if (dac_on) {
      dacWrite(PIN_BOBINA, 0);
      dacDisable(PIN_BOBINA);
      pinMode(PIN_BOBINA, OUTPUT);
      digitalWrite(PIN_BOBINA, LOW);
      dac_on = false;
    }
    bobina_d = 0;
    Serial.println("OK,BOBINA=OFF");
    return;
  }
  for (unsigned int i = 0; i < arg.length(); i++) {
    if (!isDigit(arg[i])) { Serial.println("ERR,uso: BOBINA 0-4095 | BOBINA OFF | BOBINA"); return; }
  }
  long d = arg.toInt();
  if (d < 0 || d > 4095) { Serial.println("ERR,BOBINA fuera de rango 0-4095"); return; }
  Serial.printf("OK,BOBINA=%lu\n", (unsigned long)bobinaAplicar(d));
}

long bobinaAplicar(long d) {
  if (d < 0) d = 0;
  if (d > D_MAX) d = D_MAX;
  uint32_t v8 = ((uint32_t)d * 255 + 2047) / 4095;
  dacWrite(PIN_BOBINA, (uint8_t)v8);
  dac_on = true;
  bobina_d = (v8 * 4095 + 127) / 255;
  return (long)bobina_d;
}

void comandoInfo() {
  unsigned long t0 = micros();
  long n = 0;
  while (micros() - t0 < 100000UL) { analogRead(PIN_ADC); n++; }
#ifdef ESP_ARDUINO_VERSION_STR
  const char *core = ESP_ARDUINO_VERSION_STR;
#else
  const char *core = "?";
#endif
  Serial.printf("OK,INFO,%s,core=%s,motor=%d,fs=%lu,aten=%s,sync=%d,analogRead=%.1fkS/s,dma=%d,bobina=%s,rf=%d,temp=%d\n",
                VERSION, core, motor, (unsigned long)dma_fs, aten_db == 2 ? "2.5" : String(aten_db).c_str(),
                sync_on ? 1 : 0, n / 100.0f, HAY_DMA, dac_on ? String(bobina_d).c_str() : "OFF",
                rf_on ? 1 : 0, temp_ok ? 1 : 0);
}

void modulacionTramo(int modo, int k) {
  bool alto  = (k < LOCKIN_M / 2);
  bool borde = (k == 0 || k == LOCKIN_M / 2);
  if (!borde) return;
  if (modo == 2) adfEscribir(alto ? r4_on : r4_off);
  if (modo == 4) adfEscribir(alto ? r0_fm_hi : r0_fm_lo);
  if (sync_on)   digitalWrite(PIN_SYNC, alto ? HIGH : LOW);
}

void modulacionFin(int modo) {
  if (modo == 2) { adfEscribir(r4_on); rf_on = true; }
  if (modo == 4) adfEscribir(reg[0]);
  if (sync_on)   digitalWrite(PIN_SYNC, LOW);
}

bool medirLockin(float fmod, int ciclos, int modo, int asent_ms) {
  RL.ok = false; RL.err[0] = 0;
  if (asent_ms > 0) delay(asent_ms);
#if HAY_DMA
  if (motor == 1) { lockinDMA(fmod, ciclos, modo); return RL.ok; }
#endif
  lockinAnalogRead(fmod, ciclos, modo);
  return RL.ok;
}

void comandoLockin(float fmod, int ciclos, int modo, int asent_ms) {
  if (medirLockin(fmod, ciclos, modo, asent_ms))
    Serial.printf("OK,%.3f,%.4f,%.4f,%ld\n", RL.media, RL.x, RL.y, RL.n);
  else
    Serial.printf("ERR,%s\n", RL.err);
}

void lockinAnalogRead(float fmod, int ciclos, int modo) {
  const int M = LOCKIN_M;
  const double tramo_us = 1e6 / (double)fmod / M;
  double sx = 0, sy = 0, sm = 0;
  long nmuestras = 0;
  unsigned long t0 = micros();
  for (int c = 0; c < ciclos; c++) {
    for (int k = 0; k < M; k++) {
      modulacionTramo(modo, k);
      bool descartar = (modo == 4 && fm_descarte && (k == 0 || k == M / 2));
      unsigned long fin = t0 + (unsigned long)((double)((long)c * M + k + 1) * tramo_us + 0.5);
      double suma = 0; long n = 0;
      while ((long)(micros() - fin) < 0) { suma += analogRead(PIN_ADC); n++; }
      if (n == 0 || descartar) continue;
      double v = suma / n;
      float fase = 2.0f * PI * (k + 0.5f) / M;
      sx += v * sinf(fase);
      sy += v * cosf(fase);
      sm += v;
      nmuestras += n;
    }
  }
  modulacionFin(modo);
  long tramos = (long)ciclos * M;
  if (modo == 4 && fm_descarte) tramos -= 2L * ciclos;
  RL.media = sm / tramos; RL.x = 2.0 * sx / tramos; RL.y = 2.0 * sy / tramos; RL.n = nmuestras; RL.ok = true;
}

#if HAY_DMA
#define DMA_POOL_BYTES 8192
static uint8_t dma_chunk[DMA_POOL_BYTES];
static volatile bool dma_ovf = false;

static bool IRAM_ATTR dmaOvfCb(adc_continuous_handle_t h, const adc_continuous_evt_data_t *e, void *u) {
  dma_ovf = true;
  return false;
}

void lockinDMA(float fmod, int ciclos, int modo) {
  const int M = LOCKIN_M;
  const double tramo_us = 1e6 / (double)fmod / M;
  const double dt_us = 1e6 / (double)dma_fs;
  const int canal = digitalPinToAnalogChannel(PIN_ADC);
  if (canal < 0) { snprintf(RL.err, sizeof(RL.err), "dma pin sin canal ADC"); return; }

  uint32_t frame = (uint32_t)(dma_fs / 10000UL) * SOC_ADC_DIGI_RESULT_BYTES;
  frame = ((frame + 3) / 4) * 4;
  if (frame < 8) frame = 8;
  if (frame > 1024) frame = 1024;

  adc_continuous_handle_t h = NULL;
  adc_continuous_handle_cfg_t hcfg = {};
  hcfg.max_store_buf_size = DMA_POOL_BYTES;
  hcfg.conv_frame_size = frame;
  esp_err_t err = adc_continuous_new_handle(&hcfg, &h);
  if (err != ESP_OK) { snprintf(RL.err, sizeof(RL.err), "dma new_handle %d", (int)err); return; }

  adc_digi_pattern_config_t pat = {};
  pat.atten = (uint8_t)atenEnum(aten_db);
  pat.channel = (uint8_t)canal;
  pat.unit = ADC_UNIT_1;
  pat.bit_width = SOC_ADC_DIGI_MAX_BITWIDTH;
  adc_continuous_config_t dcfg = {};
  dcfg.pattern_num = 1;
  dcfg.adc_pattern = &pat;
  dcfg.sample_freq_hz = dma_fs;
  dcfg.conv_mode = ADC_CONV_SINGLE_UNIT_1;
  dcfg.format = ADC_DIGI_OUTPUT_FORMAT_TYPE1;
  err = adc_continuous_config(h, &dcfg);
  if (err != ESP_OK) { adc_continuous_deinit(h); snprintf(RL.err, sizeof(RL.err), "dma config %d", (int)err); return; }

  adc_continuous_evt_cbs_t cbs = {};
  cbs.on_pool_ovf = dmaOvfCb;
  adc_continuous_register_event_callbacks(h, &cbs, NULL);

  double sumk[LOCKIN_M];
  long cntk[LOCKIN_M];
  for (int k = 0; k < M; k++) { sumk[k] = 0; cntk[k] = 0; }
  long invalidas = 0;
  dma_ovf = false;

  err = adc_continuous_start(h);
  if (err != ESP_OK) { adc_continuous_deinit(h); snprintf(RL.err, sizeof(RL.err), "dma start %d", (int)err); return; }

  const unsigned long t0 = micros() + 3000UL;
  const long total_tramos = (long)ciclos * M;
  const double t_fin_rel = (double)total_tramos * tramo_us;

  auto drenar = [&]() -> double {
    uint32_t total = 0, got = 0;
    while (total + 2 <= DMA_POOL_BYTES &&
           adc_continuous_read(h, dma_chunk + total, DMA_POOL_BYTES - total, &got, 0) == ESP_OK && got > 0) {
      total += got;
    }
    if (total == 0) return -1e30;
    const double ahora = (double)(long)(micros() - t0);
    const long n = total / SOC_ADC_DIGI_RESULT_BYTES;
    for (long j = 0; j < n; j++) {
      adc_digi_output_data_t *p = (adc_digi_output_data_t *)&dma_chunk[j * SOC_ADC_DIGI_RESULT_BYTES];
      if ((int)p->type1.channel != canal) { invalidas++; continue; }
      const double ts = ahora - ((double)(n - 1 - j) + 0.5) * dt_us;
      if (ts < 0 || ts >= t_fin_rel) continue;
      const long g = (long)(ts / tramo_us);
      if (g < 0 || g >= total_tramos) continue;
      const int k = (int)(g % M);
      if (modo == 4 && fm_descarte && (k == 0 || k == M / 2)) continue;
      sumk[k] += p->type1.data;
      cntk[k]++;
    }
    return ahora - 0.5 * dt_us;
  };

  while ((long)(micros() - t0) < 0) drenar();

  for (int c = 0; c < ciclos; c++) {
    for (int k = 0; k < M; k++) {
      modulacionTramo(modo, k);
      const unsigned long fin = t0 + (unsigned long)((double)((long)c * M + k + 1) * tramo_us + 0.5);
      while ((long)(micros() - fin) < 0) drenar();
    }
  }
  modulacionFin(modo);

  const unsigned long t_lim = micros() + 5000UL;
  while ((long)(micros() - t_lim) < 0) {
    if (drenar() >= t_fin_rel) break;
  }
  adc_continuous_stop(h);
  adc_continuous_deinit(h);

  if (dma_ovf) { snprintf(RL.err, sizeof(RL.err), "dma desborde (se perdieron muestras)"); return; }

  double sx = 0, sy = 0, sm = 0;
  long nmuestras = 0;
  int usados = 0;
  for (int k = 0; k < M; k++) {
    if (modo == 4 && fm_descarte && (k == 0 || k == M / 2)) continue;
    if (cntk[k] == 0) { snprintf(RL.err, sizeof(RL.err), "dma tramo %d sin muestras", k); return; }
    const double v = sumk[k] / cntk[k];
    const float fase = 2.0f * PI * (k + 0.5f) / M;
    sx += v * sinf(fase);
    sy += v * cosf(fase);
    sm += v;
    nmuestras += cntk[k];
    usados++;
  }
  if (invalidas > 0) Serial.printf("[DMA] %ld muestras con canal invalido descartadas\n", invalidas);
  RL.media = sm / usados; RL.x = 2.0 * sx / usados; RL.y = 2.0 * sy / usados; RL.n = nmuestras; RL.ok = true;
}
#endif
