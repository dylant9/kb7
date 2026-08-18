#ifndef KB7_LIGHTING_H
#define KB7_LIGHTING_H

#include "kb7/profile_blob.h"

/* Renders in controller-channel order. Physical key-to-channel correlation is
 * intentionally not guessed; global and channel-order effects remain usable. */
void kb7_lighting_render(const struct kb7_lighting_profile *profile,
                         uint32_t milliseconds,
                         const uint8_t travel[KB7_HALL_KEY_COUNT],
                         struct kb7_rgb colors[KB7_RGB_POSITION_COUNT]);

#endif
