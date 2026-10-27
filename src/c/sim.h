/* sim.h — glue shared by main.c (book CLI), ui.c (web UI engine) and buffer.c */
#ifndef SIM_H
#define SIM_H

#include <stdatomic.h>
#include "buffer.h"

#define MAX_THREADS 100

extern atomic_int  running;              /* 1 while threads should keep working */
extern atomic_long produced, consumed;   /* counted inside the critical section */
extern _Thread_local char me[16];         /* name of the current thread: P1, C2 ... */

int    sim_running(void);
double elapsed(void);                    /* seconds since start */
void   sim_on_insert(buffer_item item, int slot, int count);   /* called under mutex */
void   sim_on_remove(buffer_item item, int slot, int count);   /* called under mutex */

/* UI mode (ui.c) */
int  ui_main(int argc, char *argv[]);
void ui_on_insert(buffer_item item, int slot, int count);
void ui_on_remove(buffer_item item, int slot, int count);

#endif
