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
#ifndef KB7_ENABLE_UNVERIFIED_RECOVERY_CHORD
#define KB7_ENABLE_UNVERIFIED_RECOVERY_CHORD 0
#endif
/*
 * Re-enter the preserved flash loader using the stock sequence: relocate the
 * loader from its XIP window into PRAM, then request a PRAM software reset.
 * This remains off in ordinary builds until the dedicated proof image has
 * passed on hardware.
 */
#ifndef KB7_ENABLE_UNVERIFIED_LOADER_REENTRY
#define KB7_ENABLE_UNVERIFIED_LOADER_REENTRY 0
#endif
/* Build-only profile which invokes loader re-entry before core0_main(). */
#ifndef KB7_BUILD_LOADER_REENTRY_PROOF
#define KB7_BUILD_LOADER_REENTRY_PROOF 0
#endif
#if KB7_BUILD_LOADER_REENTRY_PROOF && !KB7_ENABLE_UNVERIFIED_LOADER_REENTRY
#error "the loader re-entry proof requires its explicit unverified feature gate"
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
#ifndef KB7_ENABLE_ACTION_BAR
#define KB7_ENABLE_ACTION_BAR 0
#endif
#ifndef KB7_ACTION_BAR_BOARD_PROFILE_VERIFIED
#define KB7_ACTION_BAR_BOARD_PROFILE_VERIFIED 0
#endif

#endif
