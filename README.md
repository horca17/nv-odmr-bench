# NV-center ODMR bench · Córdoba

A home-built bench for optically detected magnetic resonance (ODMR) with NV centers in diamond, at room temperature. Next to it is the same set of protocols emulated on IBM Quantum (the digital twin).

**Author:** Horacio S. Cáceres, independent researcher, Córdoba, Argentina.
**Companion paper (digital twin):** [10.5281/zenodo.20191912](https://doi.org/10.5281/zenodo.20191912)

## Status

The bench detected ODMR for the first time on **23 Sep 2026**. On **7 Oct 2026** a magnet test at fixed frequency confirmed the signal, while the off-resonance control stayed flat. From **17 Oct 2026** it works as a magnetometer: bias magnets split the resonance into four lines, and a frequency-modulated lock-in on one line gives a signal proportional to its shift. Since **19 Oct** the loop is closed with the current of a small coil, and since **23 Oct** the loop runs on the ESP32 itself (firmware v5.1): at power-up it checks the line and measures without a computer.

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
| Phase readout with a modulated coil, zero field | phase works as a threshold, not as a proportional measurement | 14–16 Oct |
| FM lock-in magnetometer at a fixed point (±3 MHz, 37 Hz), open loop | ~9 µT/√Hz; Allan 0.84 µT at ~2 min | 17 Oct |
| Noise budget: same noise with microwaves off and laser blocked | detection electronics dominate | 18 Oct |
| Continuous ADC readout by DMA (200 kS/s), open loop | 2.4 µT/√Hz | 18 Oct |
| Closed loop, coil current driven by the ESP32 DAC (2 h 37 min run) | 2.5 µT/√Hz; minimum Allan deviation 0.21 µT at ~4.5 min | 19 Oct |
| Minimum detectable field: 0.94 µT coil step (smallest DAC step), alternated every 60 s | detected in all 5 runs, 4.8σ to 7σ (conservative error) | 21–22 Oct |
| Closed loop on the ESP32, display on a separate supply | 1.3–1.4 µT/√Hz (2.3 with the display on the ESP32 3.3 V rail) | 23 Oct |
| Op-amp current source (LM324 + BC337, I = V_DAC / 27 Ω) | loop range +134 / −108 µT (before +78 / −65) | 23 Oct |
| Coil scale K measured with the NV (line shift vs DAC step) | 0.0688 ± 0.0007 µT/step (~2 % between sides) | 23 Oct |
| Noise with microwaves off | unchanged: the floor does not come from the NV | 23 Oct |

**Note on power:** until 12 Oct 2026 the control script always sent +2 dBm regardless of the `POTENCIA` setting (fixed on 12 Oct). Run `12Oct_1525` says −4 dBm in its metadata but was measured at +2 dBm.

**Note on noise values (22–23 Oct):** the Python loop scripts v1/v2 used the slope measured at start-up for the whole run; in a cold start that slope is ~40 % larger than the real one, which smoothed the series and underestimated the noise. From 22 Oct the slope is re-measured every 3 min. On 23 Oct the OLED display was found to add noise through the ESP32 3.3 V rail; the values before that date include it.

**Open questions:** the origin of the ~5 MHz zero-field doublet (nothing on the bench moved it), and the slow drift, which now limits the Allan deviation beyond a few minutes. With a single line, a temperature change of the diamond cannot be told apart from a field change; measuring two lines would separate them.

## Hardware

- **Diamond:** HPHT type Ib, twinned, (111) face (Element Six SC Macle); triangular plate, sides 4.0 × 4.0 × 3.0 mm, 1.0 mm thick.
- **Laser and optics:** Thorlabs L520P50 laser (520 nm, 50 mW) with its own LM317 current driver, LT240P-A collimator, FELH0550 long-pass filter.
- **Detection:** BPW34 photodiode into an OPA2134 transimpedance amplifier, read by the ESP32 ADC (GPIO34) via DMA.
- **Microwaves:** ADF435x PLL synthesizer, frequency-modulated ±3 MHz at 37 Hz, into a thin copper-wire loop, no amplifier.
- **Bias field:** hard-drive magnet over the laser axis (four lines; the lower outer line near 2833 MHz is used).
- **Coil and current source:** concentric coil, 100 turns of 0.1 mm wire (~12.5 Ω), fed from +5 V. Current set by the ESP32 DAC (GPIO25) through an LM324 + BC337 source with 27 Ω emitter resistor.
- **Temperature:** DS18B20 next to the assembly (GPIO33).
- **Display:** SSD1306 OLED on I²C, powered from a separate 3.3 V supply. Nothing with variable current draw on the ESP32 3.3 V rail.
- **Non-magnetic parts near the diamond:** ferromagnetic connectors and cables there held magnetization and shifted the reading by up to 24 µT after a magnet was brought close.
- **Control:** ESP32. Firmware v5.1 measures on its own (AUTO mode) and prints one `DATO` line per loop (~1.4 s); the Python scripts are used for alignment, calibration and tests.

## Repository layout

```
firmware/
  uncut-gem-fase1-motor-medir/   first measurement engine (sweeps), used until 13 Oct
  uncut-gem-v5.1/                current: FM lock-in, closed loop and AUTO mode on the ESP32
control/
  banco.py, odmr_*.py            sweep scripts for the first firmware
  alinear.py                     alignment in three stages (laser, magnet, coil)
  celda_registro_auto.py         logs and plots the AUTO mode (sends no commands)
  celda_escalones.py             minimum detectable field (coil steps, open loop)
  celda_calibrar_k.py            coil scale K measured with the NV
  celda_control_ruido.py         noise-floor control (normal / laser blocked / microwaves off)
  celda_lazo_temp_v3.py          closed loop from Python (firmware v4.6 / v5, BC337 source)
data/                            raw runs, named by date and time; index.csv (up to 13 Oct) and
                                 index_14-23Oct.csv (magnetometer runs)
digital-twin/                    Qiskit notebooks for the IBM Quantum emulation (paper v3)
```

The magnetometer field is computed as B = −K·(D − D0) − X / (p·γ), with D the coil DAC value, X the lock-in output, p its slope per MHz at the working point and γ = 28 GHz/T. The noise figure is σ(ΔB)/√2 · √Δt.

## Method rules

- Acceptance criteria are written down **before** looking at the data.
- Every measurement comes with a control.
- Change one variable at a time.

## Credits and license

The idea of measuring through the phase shift, in real time, came from a conversation with Matías on 9 October 2026.

The firmware started from **[Uncut Gem](https://github.com/QuantumVillage/UncutGem)** by Quantum Village, which is released under the **GNU AGPL v3**. The ADF4350 driver in this repository comes from that project. For that reason this repository is also distributed under AGPL v3.

---

**En español:** banco ODMR casero con centros NV en diamante. Primera detección el 23 de septiembre de 2026, validada con imán el 7 de octubre. Desde el 17 de octubre funciona como magnetómetro, desde el 19 en lazo cerrado y desde el 23 el ESP32 mide solo: 1,3–1,4 µT/√Hz y un escalón de 0,94 µT detectado de 4,8σ a 7σ. Acá van el firmware, los scripts, las corridas crudas y el gemelo digital en IBM Quantum.
