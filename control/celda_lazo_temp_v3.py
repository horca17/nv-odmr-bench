# %% Lazo cerrado desde Python + temperatura (firmware v4.6 / v5, fuente BC337)
# Corrige la corriente de la bobina cada vuelta (ganancia GAN) y mide la pendiente cada CADA_PEND s.
# Campo = -K_CAL * (D - D0) - X / (pendiente * gamma). Guarda lazoT3_<fecha>.npz.

D0        = 3228
K_CAL     = 0.0586
F_BUSCA   = 2833.5
SEMI      = 8.0
GAN       = 0.5
CADA_PEND = 180
TOL_PEND  = 0.5
D_MIN, D_MAX = 1600, 4095
PASO_PRUEBA  = 160
PUERTO    = "/dev/cu.usbserial-1420"   # ajustar

import os, time
import numpy as np
from IPython.display import clear_output, display
import matplotlib.pyplot as plt

DATOS = os.path.expanduser("~/Documents/Arduino/data")
os.makedirs(DATOS, exist_ok=True)

try:
    ser
    try:
        vivo = ser.is_open and ser.in_waiting >= 0
    except Exception:
        vivo = False
    if not vivo:
        try: ser.close()
        except Exception: pass
        raise NameError
except NameError:
    import serial
    ser = serial.Serial(PUERTO, 115200, timeout=5)
    time.sleep(2)
    while ser.in_waiting: ser.readline()

def volver_auto():
    """Devuelve el ESP32 (v5.1) al modo AUTO."""
    try:
        print("modo solo:", enviar("AUTO", espera=5))
    except Exception as e:
        print("no se pudo volver al modo solo:", e)

def enviar(linea, espera=10):
    """Manda un comando y devuelve la respuesta OK; si responde ERR, corta con el mensaje."""
    ser.reset_input_buffer(); ser.write((linea + "\n").encode())
    t0 = time.time()
    while time.time() - t0 < espera:
        if ser.in_waiting:
            l = ser.readline().decode(errors="ignore").strip()
            if l.startswith("OK"): return l
            if l.startswith("ERR"): raise RuntimeError(l)
    raise TimeoutError(linea)

PFD, MOD = 12.5, 25
R1 = bytes([0x00, 0x00, 0x80, 0xC9]); R2 = bytes([0x38, 0x00, 0xBE, 0x42])
R3 = bytes([0x00, 0x04, 0x00, 0x03]); R4 = bytes([0x00, 0x86, 0x43, 0x3C])
R5 = bytes([0x00, 0x58, 0x00, 0x05])
def r0_de(f):
    n = round(f / PFD * MOD); INT, FRAC = n // MOD, n % MOD
    return ((INT << 15) | (FRAC << 3)).to_bytes(4, "big")
assert r0_de(2870.0).hex() == "00728078"
def set_frecuencia(f):
    enviar(f"SET {r0_de(f).hex()} {R1.hex()} {R2.hex()} {R3.hex()} {R4.hex()} {R5.hex()}")

def fm(f, delta=3.0, ciclos=37, f_mod=37.0):
    """(media del TIA, X) con FM +-delta alrededor de f (~1 s con 37 ciclos)."""
    set_frecuencia(f)
    enviar(f"FM {r0_de(f - delta).hex()} {r0_de(f + delta).hex()} 1")
    p = enviar(f"LOCKIN {f_mod:.1f} {ciclos} 4", espera=ciclos / f_mod + 5).split(",")
    return float(p[1]), float(p[2])
def x_fm(f, ciclos=37): return fm(f, ciclos=ciclos)[1]
def poner(d):
    """BOBINA d; devuelve el valor REAL que aplica el DAC (pasos de 16)."""
    real = int(enviar(f"BOBINA {int(d)}").split("=")[1]); time.sleep(0.3)
    return real
def temp():
    """Ultima temperatura del DS18B20 (C)."""
    return float(enviar("TEMP").split(",")[1].split("=")[1])
def medir_pend(F0, n=2):
    """Pendiente de X por MHz en F0 (negativa en el centro de la loma)."""
    return float(np.mean([x_fm(F0 + 0.5) - x_fm(F0 - 0.5) for _ in range(n)]))

GAMMA = 0.028
print(enviar("MOTOR 1 200000")); d0r = poner(D0); time.sleep(2)
print(f"temperatura {temp():.2f} C")
BUSQ = np.arange(F_BUSCA - SEMI, F_BUSCA + SEMI + 0.01, 0.5)
xb = np.array([x_fm(f, ciclos=18) for f in BUSQ])
cr = [BUSQ[j] + 0.5 * xb[j] / (xb[j] - xb[j + 1]) for j in range(len(BUSQ) - 1) if xb[j] > 0 >= xb[j + 1]]
if not cr: raise RuntimeError(f"no se encontro la loma entre {BUSQ[0]} y {BUSQ[-1]} MHz")
linea = min(cr, key=lambda c: abs(c - F_BUSCA)); F0 = round(linea * 2) / 2
print(f"loma en {linea:.2f} MHz  ->  F0 = {F0}")
pend0 = float(np.mean([x_fm(F0 + 0.5) - x_fm(F0 - 0.5) for _ in range(4)]))
if pend0 >= 0: raise RuntimeError(f"pendiente {pend0:+.3f}: F0 no esta en el centro de la loma")
r, dr = [], []
for dd in (D0 + PASO_PRUEBA, D0 - PASO_PRUEBA):
    dr.append(poner(dd)); r.append(np.mean([x_fm(F0) for _ in range(8)]))
d0r = poner(D0)
k_rapido = -(r[0] - r[1]) / (dr[0] - dr[1]) / pend0 / GAMMA
print(f"pendiente {pend0:+.3f}/MHz   K rapido {k_rapido:+.4f} uT/paso   (calibrado {K_CAL:+.4f})")
if k_rapido <= 0 or not (0.5 < k_rapido / K_CAL < 2):
    print("** AVISO: el K rapido no coincide con la calibracion **")
K = K_CAL
pend = pend0
dXdD = -K * pend * GAMMA

T, DD, XX, BB, TT, LL, PU = [], [], [], [], [], [], []
PT, PV, PTT, POK = [], [], [], []
d, dreal = float(d0r), d0r
t_pend = time.time() - CADA_PEND
nombre = os.path.join(DATOS, f"lazoT3_{time.strftime('%d%b_%H%M')}.npz")
def guardar():
    if T:
        np.savez(nombre, t=np.array(T), D=np.array(DD), x=np.array(XX), B=np.array(BB), temp=np.array(TT),
                 luz=np.array(LL), pend_usada=np.array(PU), pend_t=np.array(PT), pend_v=np.array(PV),
                 pend_temp=np.array(PTT), pend_ok=np.array(POK), pend=pend0, dXdD=dXdD, K=K,
                 k_rapido=k_rapido, d0=d0r, f0=F0, linea=linea, gan=GAN)
        return nombre

def dibujar():
    n = len(T)
    t = (np.array(T) - T[0]) / 60
    fig, ax = plt.subplots(5, 1, figsize=(11, 11), sharex=True, gridspec_kw={"height_ratios": [3, 2, 2, 2, 1]})
    ax[0].plot(t, BB, "C0.", ms=3)
    if n >= 10: ax[0].plot(t[9:], np.convolve(BB, np.ones(10) / 10, "valid"), "C3", lw=1.2)
    ax[0].set_ylabel("campo (uT)")
    ruido = np.std(np.diff(BB)) / np.sqrt(2) if n > 5 else 0
    sat = "  ** DAC EN EL LIMITE **" if d in (D_MIN, D_MAX) else ""
    ax[0].set_title(f"{time.strftime('%H:%M:%S')}  n={n}  campo {BB[-1]:+.2f} uT  ruido {ruido:.2f}  T {TT[-1]:.2f} C  "
                    f"luz {LL[-1]:.0f}  pendiente en uso {pend:+.3f} (arranque {pend0:+.3f}){sat}", fontsize=10)
    ax[1].plot(t, TT, "C4.", ms=2); ax[1].set_ylabel("temp (C)")
    ax[2].plot(t, PU, "k-", lw=1, label="en uso")
    if PV:
        pt = (np.array(PT) - T[0]) / 60; ok = np.array(POK, bool); pv = np.array(PV)
        ax[2].plot(pt[ok], pv[ok], "C1o", ms=4, label="medida")
        if (~ok).any(): ax[2].plot(pt[~ok], pv[~ok], "rx", ms=6, label="descartada")
    ax[2].set_ylabel("pendiente /MHz"); ax[2].legend(fontsize=8, loc="best")
    ax[3].plot(t, LL, "C2.", ms=2); ax[3].set_ylabel("luz (TIA)")
    ax[4].plot(t, DD, "C7.", ms=2); ax[4].set_ylabel("DAC"); ax[4].set_xlabel("min")
    plt.tight_layout(); plt.show(); plt.close(fig)

try:
    while True:
        if time.time() - t_pend >= CADA_PEND:
            tc = temp(); pv = medir_pend(F0)
            ok = pv < 0 and (1 - TOL_PEND) < pv / pend < (1 + TOL_PEND)
            if ok:
                pend = pv
                dXdD = -K * pend * GAMMA
            PV.append(pv); PT.append(time.time()); PTT.append(tc); POK.append(ok)
            t_pend = time.time()
        luz, x = fm(F0)
        tc = temp()
        b_res = -x / pend / GAMMA
        b = -K * (dreal - d0r) + b_res
        T.append(time.time()); DD.append(dreal); XX.append(x); BB.append(b); TT.append(tc); LL.append(luz); PU.append(pend)
        d = min(D_MAX, max(D_MIN, d - GAN * x / dXdD))
        dreal = poner(round(d))
        n = len(T)
        if n % 30 == 0: guardar()
        if n % 3: continue
        clear_output(wait=True)
        dibujar()
except KeyboardInterrupt:
    pass
finally:
    g = guardar()
    clear_output(wait=False)
    if g: print("guardado", g, len(T), "vueltas,", len(PV), "pendientes   (la bobina queda en", dreal, ")")
    if PV: print("pendientes: " + "  ".join(f"{v:+.3f}{'' if o else '(X)'}@{c:.2f}C" for v, c, o in zip(PV, PTT, POK)))
    if len(T) > 5: dibujar()
    volver_auto()
# %%
