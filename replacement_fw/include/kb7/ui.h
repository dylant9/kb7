#ifndef KB7_UI_H
#define KB7_UI_H

#include "kb7/screen.h"

enum kb7_ui_phase { KB7_UI_DOWN = 0, KB7_UI_MOVE = 1, KB7_UI_UP = 2 };
typedef void (*kb7_action_handler_t)(const struct kb7_widget_record *widget, int16_t value,
                                     enum kb7_ui_phase phase);
void kb7_ui_init(uintptr_t framebuffer, const struct kb7_screen_store *store,
                 kb7_action_handler_t action_handler);
void kb7_ui_render(void);
void kb7_ui_touch(uint16_t x, uint16_t y, enum kb7_ui_phase phase);
bool kb7_ui_navigate(uint16_t screen_id);
uint16_t kb7_ui_active_screen(void);

#endif
