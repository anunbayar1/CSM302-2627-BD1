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
void   sim_on_insert(buffer_item item, int slot, int count, int err);   /* called under mutex */
void   sim_on_remove(buffer_item item, int slot, int count, int err);   /* err: RACE_* or 0 */
extern atomic_long lost, bad_reads;      /* RACE_OVERWRITE / RACE_EMPTY_READ seen (experiments) */
enum { WAIT_NONE, WAIT_SEM, WAIT_LOCK };
void   sim_waiting(int what);            /* the current thread starts/stops blocking on a sem / the mutex */
void   sim_lock_owner(int has);          /* the current thread took (1) / released (0) the mutex */

/* UI mode (ui.c) */
int  ui_main(int argc, char *argv[]);
void ui_on_insert(buffer_item item, int slot, int count, int err);
void ui_on_remove(buffer_item item, int slot, int count, int err);
void ui_waiting(int what);
void ui_lock_owner(int has);

#endif
