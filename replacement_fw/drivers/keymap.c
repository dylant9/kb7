#include "kb7/reports.h"

/*
 * The privately captured sensor-selector map is not redistributable here.
 * Failing closed prevents a sensor index from being mistaken for a HID usage.
 * A clean-room board profile must replace this function with a reviewed map.
 */
bool kb7_keymap_lookup(uint8_t sensor, struct kb7_hid_binding *binding) {
    (void)sensor;
    if (binding != NULL) {
        binding->usage = 0U;
        binding->modifier_mask = 0U;
    }
    return false;
}
