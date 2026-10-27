/* sim.h — glue between the buffer and main.c (run flag + event logging) */
#ifndef SIM_H
#define SIM_H

#include "buffer.h"

int  sim_running(void);
void sim_on_insert(buffer_item item, int slot, int count);   /* called under mutex */
void sim_on_remove(buffer_item item, int slot, int count);   /* called under mutex */
int  buffer_count(void);

#endif
