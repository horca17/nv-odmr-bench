#include "sweep_config.h"

#if   SWEEP_VARIANTE == 0
  #include "sweep_array_1970.h"
#elif SWEEP_VARIANTE == 1
  #include "sweep_array_025mhz.h"
#elif SWEEP_VARIANTE == 2
  #include "sweep_array_05mhz.h"
#elif SWEEP_VARIANTE == 3
  #include "sweep_array_1mhz.h"
#elif SWEEP_VARIANTE == 4
  #include "sweep_array_2mhz.h"
#elif SWEEP_VARIANTE == 5
  #include "sweep_array_4mhz.h"
#elif SWEEP_VARIANTE == 6
  #include "sweep_array_8mhz.h"
#elif SWEEP_VARIANTE == 7
  #include "sweep_array_segmentado_pfd25.h"
#endif
