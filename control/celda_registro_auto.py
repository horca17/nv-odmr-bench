# %% Registro del modo AUTO (firmware v5.1)
# Solo escucha: el ESP32 mide solo y manda una linea DATO por vuelta.
# DATO: t_s, campo_uT, D, X, temp_C, luz, pendiente, estado. Guarda auto_<fecha>.npz.

PUERTO = "/dev/cu.usbserial-1420"   # ajustar

import os, time
import numpy as np
from IPython.display import display, Pretty
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
    recien = False
except NameError:
    import serial
    ser = serial.Serial(PUERTO, 115200, timeout=2)
    recien = True
    time.sleep(2.5)

def asegurar_auto():
    ser.write(b"ESTADO\n"); t0 = time.time()
    while time.time() - t0 < 70:
        l = ser.readline().decode(errors="ignore").strip()
        if l.startswith("[AUTO]"): print(l)
        if not l.startswith("OK,ESTADO"): continue
        modo = l.split("modo=")[1].split(",")[0]
        if modo == "MAC":
            ser.write(b"AUTO\n"); r = ser.readline().decode(errors="ignore").strip()
            print("el ESP32 estaba en modo Mac ->", r, "(verifica ~1 min y mide solo)")
        else:
            print("el ESP32 ya estaba en modo solo:", modo)
        return
    print("el ESP32 no respondio a ESTADO (firmware sin v5.1?)")
asegurar_auto()

nombre = os.path.join(DATOS, f"auto_{time.strftime('%d%b_%H%M')}.npz")
C = {k: [] for k in ("t", "B", "D", "x", "temp", "luz", "pend", "sat")}
MSJ = []
ofs, t_raw_ant = 0.0, -1.0

def guardar():
    if C["t"]:
        np.savez(nombre, mensajes=np.array(MSJ), **{k: np.array(v) for k, v in C.items()})
        return nombre

H = {}
def mostrar_msj():
    txt = "\n".join(MSJ[-6:]) or "esperando..."
    if "txt" in H: H["txt"].update(Pretty(txt))
    else: H["txt"] = display(Pretty(txt), display_id=True)

def dibujar():
    t = np.array(C["t"]) / 60; B = C["B"]; n = len(B)
    fig, ax = plt.subplots(5, 1, figsize=(11, 10.5), sharex=True, gridspec_kw={"height_ratios": [3, 2, 2, 2, 1]})
    ax[0].plot(t, B, "C0.", ms=3)
    if n >= 10: ax[0].plot(t[9:], np.convolve(B, np.ones(10) / 10, "valid"), "C3", lw=1.2)
    s = np.array(C["sat"], bool)
    if s.any(): ax[0].plot(t[s], np.array(B)[s], "rx", ms=5, label="SAT")
    ruido = np.std(np.diff(B)) / np.sqrt(2) * np.sqrt(np.median(np.diff(C["t"]))) if n > 5 else 0
    ax[0].set_ylabel("campo (uT)")
    ax[0].set_title(f"{time.strftime('%H:%M:%S')}  n={n}  campo {B[-1]:+.2f} uT  ruido {ruido:.2f} uT/rtHz  "
                    f"T {C['temp'][-1]:.2f} C  luz {C['luz'][-1]:.0f}  pendiente {C['pend'][-1]:+.3f}", fontsize=10)
    ax[1].plot(t, C["temp"], "C4.", ms=2); ax[1].set_ylabel("temp (C)")
    ax[2].plot(t, C["luz"], "C2.", ms=2); ax[2].set_ylabel("luz TIA")
    ax[3].plot(t, C["pend"], "k-", lw=1); ax[3].set_ylabel("pendiente /MHz")
    ax[4].plot(t, C["D"], "C7.", ms=2); ax[4].set_ylabel("DAC"); ax[4].set_xlabel("min (desde que empezo a medir)")
    plt.tight_layout()
    if "fig" in H: H["fig"].update(fig)
    else: H["fig"] = display(fig, display_id=True)
    plt.close(fig)

print("escuchando al ESP32 (verifica ~1 min y empieza a medir)...")
try:
    while True:
        l = ser.readline().decode(errors="ignore").strip()
        if not l: continue
        if l.startswith("[AUTO]") or l.startswith("[LISTO]"):
            MSJ.append(f"{time.strftime('%H:%M:%S')} {l}"); mostrar_msj(); continue
        if not l.startswith("DATO,"): continue
        p = l.split(",")
        if len(p) < 9: continue
        try:
            v = [float(p[1]), float(p[2]), int(p[3]), float(p[4]), float(p[5]), float(p[6]), float(p[7])]
        except ValueError:
            continue
        if v[0] < t_raw_ant:
            ofs = C["t"][-1] + 1.4 - v[0] if C["t"] else 0.0
            MSJ.append(f"{time.strftime('%H:%M:%S')} (nueva verificacion: tiempo continuado)")
        t_raw_ant = v[0]; v[0] += ofs
        for k, x in zip(("t", "B", "D", "x", "temp", "luz", "pend"), v): C[k].append(x)
        C["sat"].append(p[8] == "SAT")
        n = len(C["t"])
        if n % 30 == 0: guardar()
        if n % 6: continue
        mostrar_msj(); dibujar()
except KeyboardInterrupt:
    pass
finally:
    g = guardar()
    mostrar_msj()
    if g: print("guardado", g, len(C["t"]), "lecturas")
    if len(C["t"]) > 5: dibujar()
# %%
ser.write(b"GUARDAR 2833.5 2842 0.0586\n"); time.sleep(0.5)
while ser.in_waiting: print(ser.readline().decode(errors="ignore").strip())
