#include <stdint.h>
#include <string.h>

#include "kb7/drivers.h"

int main(void) {
    uint8_t records[70];
    struct kb7_touch_frame frame;
    memset(records, 0, sizeof(records));
    records[0] = 0x81U;
    records[1] = 0x23U; /* x = 0x123 */
    records[2] = 0x02U;
    records[3] = 0x34U; /* y = 0x234 */
    records[4] = 9U;
    records[5] = 77U;
    records[14] = 0x80U;
    records[15] = 10U;
    records[16] = 0U;
    records[17] = 20U;
    records[19] = 31U;
    records[21] = 0x83U; /* x is out of the 480-pixel surface */
    records[22] = 0xffU;
    records[23] = 0U;
    records[24] = 1U;

    if (!kb7_touch_decode_records(records, 10U, &frame) || frame.count != 2U) return 1;
    if (frame.points[0].id != 0U || frame.points[0].x != 0x123U ||
        frame.points[0].y != 0x234U || frame.points[0].pressure != 77U) return 2;
    if (frame.points[1].id != 2U || frame.points[1].x != 10U ||
        frame.points[1].y != 20U || frame.points[1].pressure != 31U) return 3;
    if (kb7_touch_decode_records(NULL, 1U, &frame) ||
        kb7_touch_decode_records(records, 0U, &frame) ||
        kb7_touch_decode_records(records, 11U, &frame) ||
        kb7_touch_decode_records(records, 1U, NULL)) return 4;
    if (!kb7_touch_geometry_supported(480U, 800U) ||
        !kb7_touch_geometry_supported(479U, 799U) ||
        kb7_touch_geometry_supported(800U, 480U) ||
        kb7_touch_geometry_supported(481U, 800U)) return 5;
    return 0;
}
