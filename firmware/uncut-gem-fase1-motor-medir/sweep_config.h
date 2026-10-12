#ifndef SWEEP_CONFIG_H
#define SWEEP_CONFIG_H

#define SWEEP_VARIANTE 7

#if   SWEEP_VARIANTE == 0
  #define FREQ_BASE_OVERRIDE 1954.0f
  #define FREQ_STEP_MHZ      0.25f
#elif SWEEP_VARIANTE == 1
  #define FREQ_BASE_OVERRIDE 2854.0f
  #define FREQ_STEP_MHZ      0.25f
#elif SWEEP_VARIANTE == 2
  #define FREQ_BASE_OVERRIDE 2838.0f
  #define FREQ_STEP_MHZ      0.5f
#elif SWEEP_VARIANTE == 3
  #define FREQ_BASE_OVERRIDE 2806.0f
  #define FREQ_STEP_MHZ      1.0f
#elif SWEEP_VARIANTE == 4
  #define FREQ_BASE_OVERRIDE 2742.0f
  #define FREQ_STEP_MHZ      2.0f
#elif SWEEP_VARIANTE == 5
  #define FREQ_BASE_OVERRIDE 2614.0f
  #define FREQ_STEP_MHZ      4.0f
#elif SWEEP_VARIANTE == 6
  #define FREQ_BASE_OVERRIDE 2358.0f
  #define FREQ_STEP_MHZ      8.0f
#elif SWEEP_VARIANTE == 7

  #define FREQ_BASE_OVERRIDE 2852.0f
  #define FREQ_STEP_MHZ      0.125f
#else
  #error "SWEEP_VARIANTE invalido. Usar un valor de 0 a 7."
#endif

#endif
