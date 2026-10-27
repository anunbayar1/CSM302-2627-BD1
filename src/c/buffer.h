/* buffer.h — OS Concepts (10th ed.), Chapter 7, Programming Project 4 */
#ifndef BUFFER_H
#define BUFFER_H

typedef int buffer_item;

#ifndef BUFFER_SIZE
#define BUFFER_SIZE 5          /* default size, as in the book (make BUFFER_SIZE=10) */
#endif
#define BUFFER_MAX 20          /* the web UI may choose 1..BUFFER_MAX at run time   */

int  buffer_init(int size);           /* size <= 0 means BUFFER_SIZE; mutex, empty, full */
void buffer_destroy(void);
int  insert_item(buffer_item item);   /* 0 on success, -1 on error / shutdown */
int  remove_item(buffer_item *item);  /* 0 on success, -1 on error / shutdown */

/* read-only helpers for printing the state (UI mode) */
int  buffer_capacity(void);
int  buffer_count(void);
void buffer_snapshot(int *slots, int *has, int *in_idx, int *out_idx, int *last, int *count);
void buffer_sem_values(int *empty_v, int *full_v);
int  buffer_mutex_busy(void);

/* experiments: the same code with one classic mistake */
enum { BUG_NONE, BUG_NO_MUTEX, BUG_NO_EMPTY, BUG_NO_FULL, BUG_ORDER };
#define RACE_OVERWRITE  1   /* insert hit a slot that still held an item: that item is lost */
#define RACE_EMPTY_READ 2   /* remove read a slot that held no item: garbage / duplicate   */
void buffer_set_bug(int bug, long window_ns);   /* window: pause in the critical section (no mutex) */
int  buffer_bug(void);
int  buffer_mutex_on(void);
int  buffer_holder_blocked(void);   /* "order": a thread waits on a semaphore while holding the mutex */

#endif
