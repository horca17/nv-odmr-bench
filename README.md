# NV-center ODMR bench · Córdoba

A home-built bench for optically detected magnetic resonance (ODMR) with NV centers in diamond, at room temperature. Next to it is the same set of protocols emulated on IBM Quantum (the digital twin).

**Author:** Horacio S. Cáceres, independent researcher, Córdoba, Argentina.
**Companion paper (digital twin):** [10.5281/zenodo.20191912](https://doi.org/10.5281/zenodo.20191912)

## Status

The bench detected ODMR for the first time on **23 Sep 2026**. On **7 Oct 2026** a magnet test at fixed frequency confirmed the signal, while the off-resonance control stayed flat. On **13 Oct 2026** the loop, diamond and filter were fixed in a single block, and a microwave power series (−4, −1, +2, +5 dBm, nominal synthesizer output) was measured.

| Quantity | Value | Date |
|---|---|---|
| First ODMR detection | ~2869 MHz, 61σ–95σ | 23 Sep 2026 |
| Doublet peaks, zero applied field | 2867.30–2867.45 and 2871.80 MHz | 28 Sep – 7 Oct |
| Center separation (2-Lorentzian fit) | 5.08–5.16 MHz | 28 & 30 Sep |
| Linewidth per line (FWHM) | 3.6–4.2 MHz | 30 Sep |
| Contrast | 0.8–0.9 % | 30 Sep |
| T₂* from linewidth | ≥ 75 ns (lower bound) | 30 Sep |
| Lower flank 2866.0 MHz, with magnet (3 cycles) | −3.13 ± 0.08 counts | 7 Oct |
| Upper flank 2873.5 MHz, with magnet (3 cycles) | −1.94 ± 0.06 counts | 7 Oct |
| Off-resonance control 2818.5 MHz (3 cycles) | +0.04 ± 0.05 counts | 7 Oct |
| Contrast, microwave loop realigned (2-Lorentzian fit, normalized to optical signal) | 1.4–2.5 % | 12 Oct |
| Line amplitude vs. microwave power, −4 to +5 dBm (loop and diamond fixed) | ×1.5 per 3 dB, not saturated | 13–14 Oct |
| Linewidth per line (FWHM), −4 to +5 dBm | 2.8–3.2 MHz, no power broadening | 13–14 Oct |
| Repeatability, two consecutive runs at +5 dBm | amplitudes agree within 1 % | 13 Oct |

**Note on power:** until 12 Oct 2026 the control script always sent +2 dBm regardless of the `POTENCIA` setting (fixed on 12 Oct). Run `12Oct_1525` says −4 dBm in its metadata but was measured at +2 dBm.

**Open question:** the origin of the ~5 MHz zero-field doublet. Nothing on the bench moved it (removing nearby magnets, switching off equipment, moving power supplies away).

## Hardware

- **Diamond:** HPHT type Ib, twinned, (111) face (Element Six SC Macle); triangular plate, sides 4.0 × 4.0 × 3.0 mm, 1.0 mm thick.
- **Laser and optics:** Thorlabs L520P50 laser (520 nm, 50 mW) with its own LM317 current driver, LT240P-A collimator, FELH0550 long-pass filter.
- **Detection:** BPW34 photodiode into an OPA2134 transimpedance amplifier. The readout is differential: signal minus a reference taken with the microwaves at 2350 MHz.
- **Microwaves:** ADF435x PLL synthesizer into a thin copper-wire loop with 51 Ω in series, no amplifier.
- **Control:** an ESP32 acts as the measurement engine and receives commands over serial. All the logic (sweeps, statistics, analysis) runs in Python on the Mac.

## Repository layout

```
firmware/       ESP32 sketch (measurement engine)
control/        Python scripts that drive the bench and save each run (.npz)
data/           raw runs, named by date and time (e.g. 23Sep_1538.npz)
digital-twin/   Qiskit notebooks for the IBM Quantum emulation (paper v3)
```

## Method rules

- Acceptance criteria are written down **before** looking at the data.
- Every measurement comes with a control.
- Change one variable at a time.

## Credits and license

The firmware started from **[Uncut Gem](https://github.com/QuantumVillage/UncutGem)** by Quantum Village, which is released under the **GNU AGPL v3**. The ADF4350 driver in this repository comes from that project. For that reason this repository is also distributed under AGPL v3.

---

**En español:** banco ODMR casero con centros NV en diamante. Primera detección el 23 de septiembre de 2026, validada con imán el 7 de octubre. Acá van el firmware, los scripts, las corridas crudas y el gemelo digital en IBM Quantum.
