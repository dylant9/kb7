#include "kb7/drivers.h"

/*
 * The device-specific panel command stream and LCD-controller register profile
 * are intentionally absent from the public tree. They were recovered from a
 * privately held interoperability reference and have not passed provenance or
 * hardware validation. A contributor may add a profile only with documented
 * redistribution rights and independent hardware validation.
 */

void kb7_panel_init(void) {
}

void kb7_lcdc_set_framebuffer(uintptr_t framebuffer) {
    (void)framebuffer;
}

bool kb7_lcdc_init(uintptr_t framebuffer) {
    (void)framebuffer;
    return false;
}

void kb7_lcdc_fill(uintptr_t framebuffer, uint16_t color) {
    (void)framebuffer;
    (void)color;
}
