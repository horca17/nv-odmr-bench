# odmr_normal.py — ODMR sweep 2670–3070 MHz, 0.5 MHz step, differential against a 2350 MHz reference.

# %%
try:
    ser
except NameError:
    raise SystemExit("Run banco.py first, in the same interactive window.")

# %%
import numpy as np, matplotlib.pyplot as plt, time, glob, os, json, warnings
from datetime import datetime

F_INI, F_FIN, PASO = 2670.0, 3070.0, 0.5

F_REF      = 2350.0
POTENCIA   = -4
ANCHO      = 10.0
ANCHOS     = [10, 18, 26, 40, 60]
NV         = (2850.0, 2890.0)
TIA_OSCURIDAD = 1995.0
TIA_SIN_DIAMANTE = 1550.0
ETIQUETA   = "corrida"
ES_CALIBRACION = False
SUPERPONER = 18
MOSTRAR    = 5

PFD, MOD = 12.5, 25

R1 = bytes([0x00, 0x00, 0x80, 0xC9])
R2 = bytes([0x38, 0x00, 0xBE, 0x42])
R3 = bytes([0x00, 0x04, 0x00, 0x03])
R5 = bytes([0x00, 0x58, 0x00, 0x05])

_POT = {-4: 0x24, -1: 0x2C, 2: 0x34, 5: 0x3C}
if POTENCIA not in _POT:
    raise ValueError(f"POTENCIA debe ser una de {sorted(_POT)}")
R4 = bytes([0x00, 0x86, 0x43, _POT[POTENCIA]])

def r0_de(f):
    n    = f / PFD
    INT  = int(round(n * MOD)) // MOD
    FRAC = int(round(n * MOD)) - INT * MOD
    if not (75 <= INT <= 65535):
        raise ValueError(f"INT={INT} fuera de rango para {f} MHz")
    v = (INT << 15) | (FRAC << 3) | 0
    return bytes([(v >> 24) & 0xFF, (v >> 16) & 0xFF,
                  (v >> 8) & 0xFF, v & 0xFF]), INT, FRAC

_r0, _i, _f = r0_de(2870.0)
assert _r0 == bytes([0x00, 0x72, 0x80, 0x78]), \
    f"R0(2870) = {_r0.hex()}, deberia ser 00728078"
print(f"R0(2870) = {_r0.hex()}  INT={_i} FRAC={_f}  -> coincide con el beacon")

front = [k * PFD for k in range(int(F_INI // PFD), int(F_FIN // PFD) + 2)
         if F_INI <= k * PFD <= F_FIN]
front_nv = [f for f in front if NV[0] <= f <= NV[1]]
if front_nv:
    print(f"AVISO: fronteras de INT dentro de la ventana NV: "
          f"{', '.join(f'{f:.1f}' for f in front_nv)}  (zona con espurios)")

F = np.arange(F_INI, F_FIN + PASO/2, PASO)

TABLA, INFO = [], []

R4_DIV2 = bytes([0x00, 0x96, 0x43, 0x34])
R4_DIV1 = bytes([0x00, 0x86, 0x43, 0x34])

for f in F:
    r0, INT, FRAC = r0_de(f)
    TABLA.append([r0, R1, R2, R3, R4_DIV1, R5]); INFO.append((INT, FRAC))
REGS_REF = [r0_de(F_REF)[0], R1, R2, R3, R4_DIV1, R5]

print(f"\ntabla de {len(F)} frecuencias, primeras {MOSTRAR}:")
for i in range(MOSTRAR):
    print(f"  {F[i]:8.2f} MHz  INT={INFO[i][0]:4d} FRAC={INFO[i][1]:3d}"
          f"   R0={TABLA[i][0].hex()}")
print(f"  ref {F_REF:.2f} MHz  R0={REGS_REF[0].hex()}")

def par(regs, invertir=False):
    if invertir:
        r = medir_registros(*REGS_REF)[0]
        s = medir_registros(*regs)[0]
    else:
        s = medir_registros(*regs)[0]
        r = medir_registros(*REGS_REF)[0]
    return s, r

sig = np.zeros(len(F)); ref = np.zeros(len(F))
print(f"\nbarrido {F_INI:.0f}-{F_FIN:.0f} MHz   paso {PASO}   "
      f"potencia {POTENCIA:+d} dBm   ref {F_REF:.0f} MHz")
if ES_CALIBRACION:
    print("  CALIBRACION: rf(0) todo el barrido. Debe dar ~0.")

t0 = time.time()
try:
    if ES_CALIBRACION:
        rf(0)
    for k in range(len(F)):
        sig[k], ref[k] = par(TABLA[k], invertir=bool(k % 2))
        if ES_CALIBRACION and k % 40 == 0:
            rf(0)
        if k % 20 == 0:
            print(f"\r{F[k]:7.1f} MHz   TIA {sig[k]:7.1f}   "
                  f"d {sig[k]-ref[k]:+6.2f}   "
                  f"[{(time.time()-t0)/60:4.1f} min]   ", end="")
finally:
    rf(0)
    print("\nRF apagada (rf(0))")

dif  = sig - ref
base = dif.mean(); sd = dif.std(); d = dif - base

nivel = sig.mean(); senal_optica = TIA_SIN_DIAMANTE - nivel

sello   = datetime.now().strftime("%d%b_%H%M")
prefijo = "odmr_calib" if ES_CALIBRACION else "odmr"
archivo = f"{prefijo}_{ETIQUETA}_{sello}.npz"
np.savez(archivo, F=F, sig=sig, ref=ref,
         meta=json.dumps(dict(potencia=POTENCIA, f_ref=F_REF, paso=PASO,
                              pfd=PFD, mod=MOD, ancho=ANCHO,
                              nivel=float(nivel), tia_oscuridad=TIA_OSCURIDAD,
                              senal_optica=float(senal_optica), piso=float(sd),
                              calibracion=ES_CALIBRACION, fecha=sello,
                              hardcodeado=True)))

print(f"listo en {(time.time()-t0)/60:.1f} min  ->  {archivo}")
print(f"nivel TIA {nivel:.1f}   senal optica {senal_optica:.0f} cuentas"
      f"   (oscuridad {TIA_OSCURIDAD:.0f})")
print(f"diferencial {base:+.3f} +/- {sd:.3f} cuentas")
p = np.arange(len(F)) % 2 == 0
print(f"  orden: pares {d[p].mean():+.3f}  impares {d[~p].mean():+.3f}"
      f"  dif {d[p].mean()-d[~p].mean():+.3f}")

def filtro(dd, ancho, FF, paso):
    hw = ancho / 2.0
    n_k = int(round(4 * ancho / paso)) | 1
    x = (np.arange(n_k) - n_k // 2) * paso
    ker = 1.0 / (1.0 + (x / hw) ** 2)
    ker = ker - ker.mean(); ker = ker / np.sqrt(np.sum(ker ** 2))
    corr = np.convolve(dd, ker, mode="same")
    b = n_k // 2; corr[:b] = np.nan; corr[-b:] = np.nan
    fuera = (FF < NV[0] - 20) | (FF > NV[1] + 20); val = ~np.isnan(corr)
    return corr / np.nanstd(corr[fuera & val]), val, fuera

snr, val, fuera = filtro(d, ANCHO, F, PASO)
umbral_teo = np.sqrt(2 * np.log(max(int((F[-1]-F[0]) / ANCHO), 2)))
maximos = []
for c in sorted(glob.glob("odmr_calib_*.npz")):
    try:
        z = np.load(c, allow_pickle=True); Fc = z["F"]
        pc = float(np.median(np.diff(Fc)))
        dc = z["sig"] - z["ref"]; dc = dc - dc.mean()
        sc, vc, _ = filtro(dc, ANCHO, Fc, pc); maximos.append(np.nanmax(sc[vc]))
    except Exception:
        pass
umbral = max(maximos) if maximos else umbral_teo
origen = (f"empirico, {len(maximos)} calibraciones" if maximos else "teorico")

en_nv = (F >= NV[0]) & (F <= NV[1]) & val
j_nv = np.nanargmax(np.where(en_nv, snr, -np.inf))
j_fu = np.nanargmax(np.where(fuera & val, snr, -np.inf))
s_pto = np.nanstd(d[fuera & val])
prof = snr[j_nv] * s_pto * np.sqrt(ANCHO / PASO) / 2

print(f"\nfiltro ({ANCHO:.0f} MHz)   umbral {umbral:.2f} sigma  [{origen}]")
print(f"   candidato EN zona NV : {F[j_nv]:7.1f} MHz  {snr[j_nv]:+.2f} sigma")
print(f"   candidato FUERA      : {F[j_fu]:7.1f} MHz  {snr[j_fu]:+.2f} sigma")
print(f"   profundidad implicada: ~{prof:.2f} cuentas"
      f"   ({100*prof/senal_optica:.3f} % de la senal optica)")

print(f"\nmismo dato con otros anchos:")
print(f"   {'ancho':>6} {'zona NV':>22} {'control':>22}")
for a in ANCHOS:

    if (int(round(4 * a / PASO)) | 1) >= len(F):
        print(f"   {a:5.0f}  no entra en una ventana de {F[-1]-F[0]:.0f} MHz, se salta")
        continue
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        sa, va, fa = filtro(d, a, F, PASO)
    ea = (F >= NV[0]) & (F <= NV[1]) & va
    if not ea.any() or not (fa & va).any():
        print(f"   {a:5.0f}  sin puntos validos en esta ventana, se salta")
        continue
    ja = np.nanargmax(np.where(ea, sa, -np.inf))
    jc = np.nanargmax(np.where(fa & va, sa, -np.inf))
    print(f"   {a:5.0f}  {F[ja]:8.1f} MHz {sa[ja]:+6.2f}    "
          f"{F[jc]:8.1f} MHz {sa[jc]:+6.2f}"
          f"{' <-' if abs(a-ANCHO) < 1e-6 else ''}")

print()
if ES_CALIBRACION:
    print(f"  CALIBRACION. Maximo del filtro: {np.nanmax(snr[val]):+.2f} sigma.")
    print( "  Ese es el techo del ruido sin senal. Define el umbral.")
elif snr[j_nv] < umbral:
    print(f"  SIN DETECCION. Zona NV ({snr[j_nv]:+.2f}) no llega a {umbral:.2f}.")
elif snr[j_nv] <= snr[j_fu]:
    print(f"  SIN DETECCION. El control lo iguala o supera ({snr[j_fu]:+.2f}).")
else:
    print(f"  CANDIDATO: {F[j_nv]:.1f} MHz con {snr[j_nv]:+.2f} sigma.")
    if any(abs(F[j_nv] - fr) < 3 for fr in front):
        print( "  OJO: cae a menos de 3 MHz de una frontera de INT.")
    print( "  Repetir 3 veces sin tocar nada. Despues iman.")

lim = umbral * s_pto * np.sqrt(ANCHO / PASO) / 2
print(f"\nlimite superior: no hay dip mayor a {lim:.2f} cuentas"
      f" = {100*lim/senal_optica:.3f} % de la senal optica")

fig, ax = plt.subplots(4, 1, figsize=(14, 14), sharex=True)
ax[0].plot(F, sig, lw=.7, label="barrido")
ax[0].plot(F, ref, lw=.7, alpha=.75, label=f"referencia ({F_REF:.0f} MHz)")
ax[0].invert_yaxis(); ax[0].legend(fontsize=9); ax[0].grid(alpha=.3)
ax[0].set_ylabel("TIA crudo")
ax[0].set_title(f"Crudo — nivel {nivel:.1f}, senal optica {senal_optica:.0f} "
                f"cuentas, {POTENCIA:+d} dBm, registros hardcodeados")
ax[1].plot(F, d, lw=.8, color="k"); ax[1].axhline(0, color="red", lw=.8, alpha=.6)
ax[1].axhspan(-3*sd, 3*sd, color="gray", alpha=.15, label="±3σ punto a punto")
ax[1].legend(fontsize=8, loc="lower right"); ax[1].grid(alpha=.3)
ax[1].set_ylabel("barrido − referencia")
ax[1].set_title(f"Diferencial — pedestal {base:+.2f}, piso ±{sd:.2f} cuentas")
ax[2].plot(F, snr, lw=1.2, color="#1F3864")
ax[2].axhline( umbral, color="red", ls="--", lw=1, label=f"umbral {umbral:.2f}σ")
ax[2].axhline(-umbral, color="red", ls="--", lw=1)
ax[2].plot(F[j_nv], snr[j_nv], "o", color="darkgreen", ms=7)
ax[2].plot(F[j_fu], snr[j_fu], "o", color="darkorange", ms=7)
ax[2].legend(fontsize=9); ax[2].grid(alpha=.3)
ax[2].set_ylabel(f"σ (filtro {ANCHO:.0f} MHz)")
ax[2].set_title("Forma de dip — verde: zona NV, naranja: control "
                "(lineas rojas punteadas = fronteras de INT)")
previas = [a for a in sorted(glob.glob("odmr_*.npz"))
           if os.path.basename(a) != os.path.basename(archivo)][-SUPERPONER:]
n_dib = 0
for a in previas:
    try:
        z = np.load(a, allow_pickle=True); Fa = z["F"]
        if len(Fa) != len(F) or abs(Fa[0]-F[0]) > 1e-6: continue
        da = z["sig"] - z["ref"]; da = da - da.mean()
        sa, _, _ = filtro(da, ANCHO, Fa, PASO)
        eti = os.path.basename(a).replace(".npz", "")
        est = dict(lw=.9, alpha=.55)
        if "calib" in eti: est.update(color="gray", ls=":")
        ax[3].plot(Fa, sa, label=eti, **est); n_dib += 1
    except Exception:
        pass
ax[3].plot(F, snr, lw=1.8, color="#1F3864", label="esta corrida")
ax[3].axhline(umbral, color="red", ls="--", lw=1)
ax[3].axhline(-umbral, color="red", ls="--", lw=1)
ax[3].legend(fontsize=7, ncol=2); ax[3].grid(alpha=.3)
ax[3].set_ylabel(f"σ (filtro {ANCHO:.0f} MHz)"); ax[3].set_xlabel("MHz")
ax[3].set_title(f"Repetibilidad — {n_dib} corridas previas")
for a_ in ax:
    a_.axvspan(*NV, color="green", alpha=.08)
    a_.axvline(2870, color="green", ls=":", lw=1.2)
    for fr in front:
        a_.axvline(fr, color="crimson", ls="--", lw=.8, alpha=.4)
plt.tight_layout(); plt.show()
