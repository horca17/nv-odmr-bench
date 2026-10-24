# %% Control del piso de ruido
# Cuatro fases de T_FASE s: normal, laser tapado, microondas apagadas, normal.
# Si el ruido de X es el mismo en las cuatro, el piso es electronico.

D0      = 1863
F_BUSCA = 2833.5
T_FASE  = 300
PUERTO  = "/dev/cu.usbserial-1420"   # ajustar

import os, time
import numpy as np

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
R3 = bytes([0x00, 0x04, 0x00, 0x03]); R5 = bytes([0x00, 0x58, 0x00, 0x05])
R4_ON  = bytes([0x00, 0x86, 0x43, 0x3C])
R4_OFF = bytes([0x00, 0x86, 0x43, 0x1C])
def r0_de(f):
    n = round(f / PFD * MOD); INT, FRAC = n // MOD, n % MOD
    return ((INT << 15) | (FRAC << 3)).to_bytes(4, "big")
RF = {"r4": R4_ON}
def xfm(f, delta=3.0, ciclos=37, fm=37.0):
    """(luz, X) del lock-in con FM +-delta alrededor de f."""
    enviar(f"SET {r0_de(f).hex()} {R1.hex()} {R2.hex()} {R3.hex()} {RF['r4'].hex()} {R5.hex()}")
    enviar(f"FM {r0_de(f - delta).hex()} {r0_de(f + delta).hex()} 1")
    p = enviar(f"LOCKIN {fm:.1f} {ciclos} 4", espera=ciclos / fm + 5).split(",")
    return float(p[1]), float(p[2])

GAMMA = 0.028
print(enviar("MOTOR 1 200000"))
print(enviar(f"BOBINA {D0}")); time.sleep(1)

BUSQ = np.arange(F_BUSCA - 8, F_BUSCA + 8.01, 0.5)
xb = np.array([xfm(f, ciclos=18)[1] for f in BUSQ])
cr = [BUSQ[j] + 0.5 * xb[j] / (xb[j] - xb[j + 1]) for j in range(len(BUSQ) - 1) if xb[j] > 0 >= xb[j + 1]]
if not cr: raise RuntimeError(f"no hay loma entre {BUSQ[0]} y {BUSQ[-1]} MHz")
linea = min(cr, key=lambda c: abs(c - F_BUSCA)); F0 = round(linea * 2) / 2
pend = np.mean([xfm(F0 + 0.5)[1] - xfm(F0 - 0.5)[1] for _ in range(3)])
if pend >= 0: raise RuntimeError(f"pendiente {pend:+.3f}: F0 no quedo en el centro de la loma")
print(f"loma {linea:.2f} MHz  F0 = {F0}  pendiente {pend:+.3f}/MHz  (se usa en las 4 fases)\n")

def ruido(x, t):
    """sigma(dX)/sqrt2 * sqrt(dt): ruido de X por raiz de Hz, y en uT con la pendiente de la fase 1."""
    rx = np.std(np.diff(x)) / np.sqrt(2) * np.sqrt(np.median(np.diff(t)))
    return rx, rx / abs(pend) / GAMMA

FASES = [("NORMAL", None), ("LASER TAPADO", "Tapa el laser y apreta Enter"),
         ("RF APAGADA", "Destapa el laser y apreta Enter (la celda apaga la RF sola)"), ("NORMAL", None)]
nombre = os.path.join(os.path.expanduser("~/Documents/Arduino/data"), f"control_{time.strftime('%d%b_%H%M')}.npz")
DATOS = {}
try:
    for k, (fase, aviso) in enumerate(FASES):
        if aviso: input(f">>> {aviso}: ")
        RF["r4"] = R4_OFF if fase == "RF APAGADA" else R4_ON
        T, L, X = [], [], []; t_ini = time.time()
        while time.time() - t_ini < T_FASE:
            luz, x = xfm(F0); T.append(time.time()); L.append(luz); X.append(x)
        T, L, X = map(np.array, (T, L, X)); DATOS[f"fase{k + 1}"] = np.vstack([T, L, X])
        rx, ru = ruido(X, T)
        print(f"{time.strftime('%H:%M:%S')}  fase {k + 1} {fase:13s}  luz {L.mean():6.0f}  X medio {X.mean():+.3f}"
              f"  ruido X {rx:.4f} /rtHz  = {ru:.2f} uT/rtHz  ({len(X)} lecturas)")
except KeyboardInterrupt:
    print("\ncortado")
finally:
    RF["r4"] = R4_ON
    np.savez(nombre, f0=F0, pend=pend, d0=D0, fases=np.array([f for f, _ in FASES]), **DATOS)
    print("guardado", nombre)
    volver_auto()
# %%
