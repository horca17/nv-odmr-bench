# banco.py — serial link to the ESP32 measurement firmware and base commands.
# Run first; the other scripts use this session.

# %%
import os
DATOS = os.path.abspath(os.path.join("..", "data"))
os.makedirs(DATOS, exist_ok=True)
os.chdir(DATOS)
print("Las corridas se guardan y se leen en:", DATOS)

# %%
import serial
import time
import numpy as np
import matplotlib.pyplot as plt

PUERTO = "/dev/cu.usbserial-1420"
BAUD = 115200

ser = serial.Serial(PUERTO, BAUD, timeout=5)
time.sleep(2)

while ser.in_waiting:
    print(ser.readline().decode(errors='ignore').strip())

# %%
def enviar_comando(cmd, timeout=5):
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode())
    t0 = time.time()
    while time.time() - t0 < timeout:
        if ser.in_waiting:
            linea = ser.readline().decode(errors='ignore').strip()
            if linea.startswith("OK,"):
                partes = linea.split(",")
                return float(partes[1]), float(partes[2]), float(partes[3])
            elif linea.startswith("ERR,"):
                raise RuntimeError(f"ESP32 error: {linea}")

    raise TimeoutError(f"Sin respuesta del ESP32 para: {cmd}")

def enviar_comando_simple(cmd, timeout=5):
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode())
    t0 = time.time()
    while time.time() - t0 < timeout:
        if ser.in_waiting:
            linea = ser.readline().decode(errors='ignore').strip()
            if linea.startswith("OK"):
                return linea
            elif linea.startswith("ERR"):
                raise RuntimeError(f"ESP32 error: {linea} "
                                   f"(¿esta flasheado el motor-rf? RF solo existe ahi)")
    raise TimeoutError(f"Sin respuesta del ESP32 para: {cmd}")

def medir_paso(n):
    return enviar_comando(f"PASO {n}")

def medir_registros(r0, r1, r2, r3, r4, r5):
    cmd = f"REG {r0.hex()} {r1.hex()} {r2.hex()} {r3.hex()} {r4.hex()} {r5.hex()}"
    return enviar_comando(cmd)

def rf(estado):
    print(enviar_comando_simple(f"RF {1 if estado else 0}"))

print("Funciones listas. Probando con un paso de ejemplo...")
prom, mn, mx = medir_paso(64)
print(f"Paso 64: prom={prom}  min={mn}  max={mx}")

# %%
def modo_live():
    ser.reset_input_buffer()
    ser.write(b"LIVE\n")
    print("Modo LIVE activo. Mové el láser buscando el DELTA más alto.")
    print("Para terminar: interrumpí esta celda (Ctrl+C o el botón de stop).\n")
    try:
        while True:
            if ser.in_waiting:
                linea = ser.readline().decode(errors='ignore').strip()
                if linea.startswith("TIA75="):
                    print(f"\r{linea}", end="")
    except KeyboardInterrupt:
        print("\n\nCerrando modo LIVE...")
        ser.write(b"si\n")
        time.sleep(0.5)

        while ser.in_waiting:
            print(ser.readline().decode(errors='ignore').strip())
        print("Modo LIVE cerrado. Listo para medir.")

# %%
modo_live()

# %%
PFD = 25

TEMPLATE_R2 = bytes([0x38, 0x00, 0x7E, 0x42])
TEMPLATE_R3 = bytes([0x00, 0x04, 0x00, 0x03])
TEMPLATE_R4 = bytes([0x00, 0x8C, 0x83, 0x24])
TEMPLATE_R5 = bytes([0x00, 0x58, 0x00, 0x05])

def calcular_registros(freq_mhz, mod=200):
    n_total = freq_mhz / PFD
    INT = int(n_total)
    frac_dec = n_total - INT
    FRAC = round(frac_dec * mod)
    if FRAC >= mod:
        FRAC = 0; INT += 1
    r0_val = (INT << 15) | (FRAC << 3) | 0
    r1_val = (1 << 15) | (mod << 3) | 1
    r0 = r0_val.to_bytes(4, 'big')
    r1 = r1_val.to_bytes(4, 'big')
    return r0, r1, TEMPLATE_R2, TEMPLATE_R3, TEMPLATE_R4, TEMPLATE_R5

def medir_frecuencia(freq_mhz):
    r0,r1,r2,r3,r4,r5 = calcular_registros(freq_mhz)
    return medir_registros(r0,r1,r2,r3,r4,r5)
