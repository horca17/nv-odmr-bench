# %% Calibracion de K (uT por paso del DAC) con el NV
# Mide la frecuencia de la linea para D0 y D0 +- OFFSETS; K = |MHz por paso| / gamma (28 GHz/T).
# Imprime la linea GUARDAR para el firmware; no la graba sola.

D0        = 1863
F_BUSCA   = 2833.5
OFFSETS   = [160, -160, 320, -320, 480, -480]
N_PASADAS = 2
PUERTO    = "/dev/cu.usbserial-1420"   # ajustar

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

def enviar(linea, espera=10):
    ser.reset_input_buffer(); ser.write((linea + "\n").encode())
    t0 = time.time()
    while time.time() - t0 < espera:
        if ser.in_waiting:
            l = ser.readline().decode(errors="ignore").strip()
            if l.startswith("OK"): return l
            if l.startswith("ERR"): raise RuntimeError(l)
    raise TimeoutError(linea)

def volver_auto():
    try:
        print("modo solo:", enviar("AUTO", espera=5))
    except Exception as e:
        print("no se pudo volver al modo solo:", e)

PFD, MOD = 12.5, 25
R1 = bytes([0x00, 0x00, 0x80, 0xC9]); R2 = bytes([0x38, 0x00, 0xBE, 0x42])
R3 = bytes([0x00, 0x04, 0x00, 0x03]); R4 = bytes([0x00, 0x86, 0x43, 0x3C])
R5 = bytes([0x00, 0x58, 0x00, 0x05])
def r0_de(f):
    n = round(f / PFD * MOD); INT, FRAC = n // MOD, n % MOD
    return ((INT << 15) | (FRAC << 3)).to_bytes(4, "big")
def xfm(f, delta=3.0, ciclos=37, fm=37.0):
    enviar(f"SET {r0_de(f).hex()} {R1.hex()} {R2.hex()} {R3.hex()} {R4.hex()} {R5.hex()}")
    enviar(f"FM {r0_de(f - delta).hex()} {r0_de(f + delta).hex()} 1")
    return float(enviar(f"LOCKIN {fm:.1f} {ciclos} 4", espera=ciclos / fm + 5).split(",")[2])
def poner(d):
    real = int(enviar(f"BOBINA {int(d)}").split("=")[1]); time.sleep(0.5)
    return real

GAMMA = 0.028
def cruce(f_aprox):
    """Frecuencia de la linea: X en la grilla de 0,5 MHz alrededor de f_aprox, recta, cruce por cero."""
    for _ in range(2):
        c = round(f_aprox * 2) / 2
        fs = np.arange(c - 1.0, c + 1.01, 0.5)
        xs = np.array([xfm(f) for f in fs])
        a, b = np.polyfit(fs, xs, 1)
        if a >= 0: raise RuntimeError(f"pendiente {a:+.3f} en el cruce: la linea se fue de la ventana")
        f_aprox = -b / a
    return f_aprox, a

try:
    print(enviar("MOTOR 1 200000"))
    d0 = poner(D0)
    BUSQ = np.arange(F_BUSCA - 8, F_BUSCA + 8.01, 0.5)
    xb = np.array([xfm(f, ciclos=18) for f in BUSQ])
    cr = [BUSQ[j] + 0.5 * xb[j] / (xb[j] - xb[j + 1]) for j in range(len(BUSQ) - 1) if xb[j] > 0 >= xb[j + 1]]
    if not cr: raise RuntimeError(f"no hay loma entre {BUSQ[0]} y {BUSQ[-1]} MHz")
    f_ant = min(cr, key=lambda c: abs(c - F_BUSCA))
    print(f"loma {f_ant:.2f} MHz.  {N_PASADAS} pasadas x {len(OFFSETS)} puntos (~8 min)\n")

    secuencia = []
    for p in range(N_PASADAS):
        for o in OFFSETS: secuencia += [0, o]
    secuencia += [0]
    T, DD, FF = [], [], []
    for k, o in enumerate(secuencia):
        d = poner(d0 + o)
        f, a = cruce(f_ant); f_ant = f
        T.append(time.time()); DD.append(d); FF.append(f)
        print(f"{time.strftime('%H:%M:%S')}  {k + 1:2d}/{len(secuencia)}  DAC {d:4d} ({d - d0:+4d})  linea {f:9.3f} MHz  pendiente {a:+.3f}")
    T, DD, FF = map(np.array, (T, DD, FF))

    dD, dF = [], []
    for i in range(1, len(DD) - 1, 2):
        dD.append(DD[i] - (DD[i - 1] + DD[i + 1]) / 2); dF.append(FF[i] - (FF[i - 1] + FF[i + 1]) / 2)
    dD, dF = np.array(dD), np.array(dF)
    (s, c0), cov = np.polyfit(dD, dF, 1, cov=True)
    es = np.sqrt(cov[0, 0]); res = dF - (s * dD + c0)
    K, eK = abs(s) / GAMMA, es / GAMMA
    print("\ncambio DAC  ->  corrimiento de la linea (MHz) y residuo (uT)")
    for x, y, r in sorted(zip(dD, dF, res)): print(f"   {x:+6.0f}   {y:+.3f}   {r / GAMMA:+.2f}")
    print(f"\nK = {K:.4f} +- {eK:.4f} uT por paso   ({100 * eK / K:.1f} %)   signo de la recta: {'+' if s > 0 else '-'}")
    print(f"deriva de la linea en D0 durante la calibracion: {(FF[::2].max() - FF[::2].min()) / GAMMA:.1f} uT")
    nombre = os.path.join(os.path.expanduser("~/Documents/Arduino/data"), f"calK_{time.strftime('%d%b_%H%M')}.npz")
    np.savez(nombre, t=T, D=DD, f=FF, dD=dD, dF=dF, K=K, eK=eK, d0=d0)
    print("guardado", nombre)
    print("\nSi convence, para guardarlo en el ESP32 (copiar la linea entera):")
    print(f'ser.reset_input_buffer(); ser.write(b"GUARDAR {F_BUSCA} {d0} {K:.4f}\\n"); time.sleep(1.5); print([l for l in ser.read(ser.in_waiting).decode(errors="ignore").splitlines() if l.startswith("OK")])')
except KeyboardInterrupt:
    print("\ncortado")
finally:
    try: poner(D0)
    except Exception: pass
    volver_auto()
# %%
