# %% Alinear el banco (lazo abierto)
# ETAPA 1: laser, sin iman ni bobina: maximizar el dip del doblete cerca de 2870 MHz.
# ETAPA 2: iman: barrido FM 2810-2920 MHz, lista las cuatro lineas mas altas.
# ETAPA 3: bobina: centra la linea elegida en F0 y, si GUARDAR_AL_FINAL, graba F0/D0/K en el ESP32 y lo deja midiendo.

ETAPA   = 3
D_BASE  = 1863
F_LINEA = 2833.5
K_CAL   = 0.0688
GUARDAR_AL_FINAL = True
PUERTO  = "/dev/cu.usbserial-1420"   # ajustar

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

def media(f, ciclos=9, fm=37.0):
    """Media del TIA a la frecuencia f, sin modular (LOCKIN modo 0)."""
    set_frecuencia(f)
    return float(enviar(f"LOCKIN {fm:.1f} {ciclos} 0", espera=ciclos / fm + 5).split(",")[1])

def xfm(f, delta=3.0, ciclos=9, fm=37.0):
    """X del lock-in con FM +-delta alrededor de f (LOCKIN modo 4): la curva en S."""
    set_frecuencia(f)
    enviar(f"FM {r0_de(f - delta).hex()} {r0_de(f + delta).hex()} 1")
    return float(enviar(f"LOCKIN {fm:.1f} {ciclos} 4", espera=ciclos / fm + 5).split(",")[2])

def poner(d):
    """BOBINA d; devuelve el valor REAL que aplica el DAC (pasos de 16)."""
    real = int(enviar(f"BOBINA {int(d)}").split("=")[1]); time.sleep(0.3)
    return real

print(enviar("MOTOR 1 200000"))
GAMMA, F_REF = 0.028, 2350.0
k = 0
try:
    if ETAPA == 1:
        print(f"BOBINA -> {poner(0)}  (sin corriente)")
        F1 = np.arange(2862.0, 2878.01, 1.0)
        f_pico, maximo = None, 0.0
        while True:
            ref = media(F_REF)
            if f_pico is None or k % 15 == 0:
                d = np.array([media(f) - ref for f in F1])
                f_pico = F1[d.argmax()]
            dip = np.mean([media(f) - ref for f in (f_pico - 0.5, f_pico, f_pico + 0.5)])
            maximo = max(maximo, dip); k += 1
            print(f"{time.strftime('%H:%M:%S')}  dip {dip:6.2f}  en {f_pico:.1f} MHz   maximo {maximo:6.2f}   luz {ref:.0f}")

    elif ETAPA == 2:
        print(f"BOBINA -> {poner(D_BASE)}")
        F2 = np.arange(2810.0, 2920.01, 2.0)
        mejor = 0.0
        while True:
            X = np.array([xfm(f) for f in F2]); k += 1
            cand = []
            for j in range(len(F2) - 1):
                if X[j] > 0 >= X[j + 1]:
                    c = F2[j] + 2.0 * X[j] / (X[j] - X[j + 1])
                    a, b = max(0, j - 2), min(len(F2), j + 4)
                    cand.append((X[a:b].max() - X[a:b].min(), c))
            top = sorted(sorted(cand, reverse=True)[:4], key=lambda z: z[1])
            if top: mejor = max(mejor, top[0][0])
            print(f"{time.strftime('%H:%M:%S')}  pasada {k:3d}   " + "   ".join(f"{c:7.1f} ({h:.2f})" for h, c in top)
                  + f"     mejor 1ra loma {mejor:.2f}")

    elif ETAPA == 3:
        d = float(poner(D_BASE)); time.sleep(1)
        BUSQ = np.arange(F_LINEA - 8, F_LINEA + 8.01, 0.5)
        xb = np.array([xfm(f, ciclos=18) for f in BUSQ])
        cr = [BUSQ[j] + 0.5 * xb[j] / (xb[j] - xb[j + 1]) for j in range(len(BUSQ) - 1) if xb[j] > 0 >= xb[j + 1]]
        if not cr: raise RuntimeError(f"no hay loma entre {BUSQ[0]} y {BUSQ[-1]} MHz: revisar F_LINEA (etapa 2)")
        linea = min(cr, key=lambda c: abs(c - F_LINEA))
        F0 = round(linea * 2) / 2
        pend = np.mean([xfm(F0 + 0.5, ciclos=37) - xfm(F0 - 0.5, ciclos=37) for _ in range(3)])
        if pend >= 0: raise RuntimeError(f"pendiente {pend:+.3f}: F0 no quedo en el centro de una loma")
        print(f"loma en {linea:.2f} MHz  ->  F0 = {F0}   pendiente {pend:+.3f}/MHz")
        dXdD = -K_CAL * pend * GAMMA
        dentro = 0
        while True:
            x = xfm(F0, ciclos=37); k += 1
            corr = -x / pend
            print(f"{time.strftime('%H:%M:%S')}  DAC {int(d)}   linea - F0 = {corr:+.3f} MHz ({corr / GAMMA:+.1f} uT)")
            dentro = dentro + 1 if abs(corr) < 0.05 else 0
            if dentro >= 5:
                print(f"\nCENTRADA en F0 = {F0} MHz.  Para el lazo: D0 = {int(d)},  F_BUSCA = {F0}")
                if GUARDAR_AL_FINAL:
                    try:
                        print(enviar(f"GUARDAR {F0} {int(d)} {K_CAL}", espera=5))
                        print(enviar("AUTO", espera=5), "-> el ESP32 verifica (~1 min) y mide solo")
                    except Exception as e:
                        print("no se guardo (firmware sin GUARDAR/AUTO?):", e)
                else:
                    print("GUARDAR_AL_FINAL = False: no se guardo nada")
                break
            d = min(4095, max(0, d - 0.5 * x / dXdD))
            d = poner(round(d))
    else:
        print("ETAPA tiene que ser 1, 2 o 3")
except KeyboardInterrupt:
    print("\ncortado")
# %%
