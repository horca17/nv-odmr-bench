# %% Campo minimo detectable
# Lazo abierto. Alterna la bobina entre D0 y D0 + PASO cada T_ESTADO s; el campo se mide con el NV
# (X / pendiente / gamma), sin usar K_CAL. Cada escalon se compara con el promedio de sus vecinos.

D0       = 1863
F_BUSCA  = 2833.5
K_CAL    = 0.0688
PASO     = 16
T_ESTADO = 60
N_CICLOS = 5
DESCARTE = 5
PUERTO   = "/dev/cu.usbserial-1420"   # ajustar

import time
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
def xfm(f, delta=3.0, ciclos=37, fm=37.0):
    """X del lock-in con FM +-delta alrededor de f (~1 s con 37 ciclos)."""
    set_frecuencia(f)
    enviar(f"FM {r0_de(f - delta).hex()} {r0_de(f + delta).hex()} 1")
    return float(enviar(f"LOCKIN {fm:.1f} {ciclos} 4", espera=ciclos / fm + 5).split(",")[2])
def poner(d):
    """BOBINA d; devuelve el valor REAL que aplica el DAC (pasos de 16)."""
    real = int(enviar(f"BOBINA {int(d)}").split("=")[1]); time.sleep(0.3)
    return real

GAMMA = 0.028
print(enviar("MOTOR 1 200000"))
d_apag = poner(D0); time.sleep(1)

BUSQ = np.arange(F_BUSCA - 8, F_BUSCA + 8.01, 0.5)
xb = np.array([xfm(f, ciclos=18) for f in BUSQ])
cr = [BUSQ[j] + 0.5 * xb[j] / (xb[j] - xb[j + 1]) for j in range(len(BUSQ) - 1) if xb[j] > 0 >= xb[j + 1]]
if not cr: raise RuntimeError(f"no hay loma entre {BUSQ[0]} y {BUSQ[-1]} MHz")
linea = min(cr, key=lambda c: abs(c - F_BUSCA)); F0 = round(linea * 2) / 2
pend = np.mean([xfm(F0 + 0.5) - xfm(F0 - 0.5) for _ in range(3)])
if pend >= 0: raise RuntimeError(f"pendiente {pend:+.3f}: F0 no quedo en el centro de la loma")
d_pren = poner(D0 + PASO); poner(D0)
aplicado = (d_pren - d_apag) * K_CAL
print(f"loma {linea:.2f} MHz  F0 = {F0}  pendiente {pend:+.3f}/MHz")
print(f"escalon: DAC {d_apag} -> {d_pren}  = {aplicado:.2f} uT aplicados (con K_CAL)")
print(f"{N_CICLOS} ciclos de {T_ESTADO} s por estado: ~{(2 * N_CICLOS + 1) * T_ESTADO / 60:.0f} min\n")

T, B, E = [], [], []
import os
os.makedirs(os.path.expanduser("~/Documents/Arduino/data"), exist_ok=True)
nombre = os.path.join(os.path.expanduser("~/Documents/Arduino/data"), f"escalones_{time.strftime('%d%b_%H%M')}.npz")
estados = [0, 1] * N_CICLOS + [0]
medias = []
try:
    for k, e in enumerate(estados):
        poner(d_pren if e else d_apag)
        t_ini = time.time(); bs = []
        while time.time() - t_ini < T_ESTADO:
            b = -xfm(F0) / pend / GAMMA
            T.append(time.time()); B.append(b); E.append(e)
            if time.time() - t_ini > DESCARTE: bs.append(b)
        m, s = np.mean(bs), np.std(bs) / np.sqrt(len(bs))
        medias.append(m)
        print(f"{time.strftime('%H:%M:%S')}  estado {k + 1:2d}/{len(estados)}  {'PRENDIDO' if e else 'APAGADO '}"
              f"  campo {m:+7.2f} +- {s:.2f} uT  ({len(bs)} lecturas)")
except KeyboardInterrupt:
    print("\ncortado")
finally:
    poner(d_apag)
    np.savez(nombre, t=np.array(T), B=np.array(B), estado=np.array(E), f0=F0, pend=pend,
             d_apag=d_apag, d_pren=d_pren, K=K_CAL, aplicado=aplicado, t_estado=T_ESTADO)
    print("guardado", nombre, "  (la bobina queda en", d_apag, ")")

dif = [medias[i] - (medias[i - 1] + medias[i + 1]) / 2 for i in range(1, len(medias) - 1, 2)]
if len(dif) >= 2:
    md, ed = np.mean(dif), np.std(dif, ddof=1) / np.sqrt(len(dif))
    print("\ndiferencias por ciclo (uT): " + "  ".join(f"{x:+.2f}" for x in dif))
    print(f"campo medido {md:+.2f} +- {ed:.2f} uT   (aplicado {aplicado:.2f} uT)   relacion {abs(md) / ed:.1f} sigma")
    print("DETECTADO a 3 sigma" if abs(md) > 3 * ed else "NO detectado a 3 sigma")
else:
    print("pocos ciclos completos para el resultado")
volver_auto()
# %%
