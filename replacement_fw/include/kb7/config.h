#ifndef KB7_CONFIG_H
#define KB7_CONFIG_H

/*
 * Public builds are deliberately passive.  A board profile may enable a
 * peripheral only after its pins, electrical mode, packet format, and recovery
 * behavior have been independently validated on hardware.
 */
#ifndef KB7_ENABLE_UNVERIFIED_DRAM_INIT
#define KB7_ENABLE_UNVERIFIED_DRAM_INIT 0
#endif
#ifndef KB7_ENABLE_DISPLAY
#define KB7_ENABLE_DISPLAY 0
#endif
#ifndef KB7_ENABLE_TOUCH
#define KB7_ENABLE_TOUCH 0
#endif
#ifndef KB7_ENABLE_RGB
#define KB7_ENABLE_RGB 0
#endif
#ifndef KB7_ENABLE_MCU2
#define KB7_ENABLE_MCU2 0
#endif
#ifndef KB7_ENABLE_ENCODER
#define KB7_ENABLE_ENCODER 0
#endif

#endif
