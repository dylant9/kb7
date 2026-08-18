#ifndef KB7_MCU2_PROTOCOL_H
#define KB7_MCU2_PROTOCOL_H

#include "kb7/drivers.h"

/* Enabling the code path is not proof of PCB ownership. A board profile may
 * set this only after continuity and passive stock-bus checks pass. */
#ifndef KB7_MCU2_BOARD_PROFILE_VERIFIED
#define KB7_MCU2_BOARD_PROFILE_VERIFIED 0
#endif

bool kb7_mcu2_command_supported(uint8_t command);
void kb7_mcu2_build_request(uint8_t command, uint8_t subcommand, uint8_t argument,
                            uint8_t request[KB7_MCU2_FRAME_SIZE]);
bool kb7_mcu2_request_valid(const uint8_t request[KB7_MCU2_FRAME_SIZE]);

#endif
