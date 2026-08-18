#ifndef KB7_APPLICATION_H
#define KB7_APPLICATION_H

#include "kb7/host_protocol.h"

/* USB OUT/feature dispatch hook. The USB owner calls this from poll context. */
bool kb7_application_handle_host_report(const void *data, uint16_t length);

#endif
