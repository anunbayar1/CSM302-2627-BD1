/*
 * buffer.c — bounded buffer for the producer–consumer problem
 * (OS Concepts, Section 7.1.1, Figures 7.1, 7.2 and 7.14).
 *
 *   empty : counting semaphore, number of empty slots   (starts at size)
 *   full  : counting semaphore, number of full slots    (starts at 0)
 *   mutex : pthread mutex lock protecting the circular queue itself
 *
 * Experiments (buffer_set_bug): the same code with one classic mistake, to see
 * what goes wrong — BUG_NO_MUTEX, BUG_NO_EMPTY, BUG_NO_FULL, BUG_ORDER (deadlock).
 * occ[] is only a checker (atomic, outside the algorithm): it records which slots
 * really hold an item, so a lost item or a read of an empty slot can be reported.
 */
#include <errno.h>
#include <pthread.h>
#include <semaphore.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#include "buffer.h"
#include "sim.h"

/* the buffer: a circular queue */
static buffer_item buffer[BUFFER_MAX];
static int size = BUFFER_SIZE;
static int in = 0, out = 0, count = 0, last = -1;

static pthread_mutex_t mutex;
static sem_t empty;
static sem_t full;
static atomic_int mutex_busy = 0;     /* only for the picture: is someone inside? */

static atomic_int bug = BUG_NONE;
static atomic_int occ[BUFFER_MAX];
static atomic_int holder_blocked = 0;    /* "order": the mutex holder is waiting on a semaphore */
static long race_ns = 0;              /* pause inside the critical section when the mutex is off */

void buffer_set_bug(int b, long window_ns) { atomic_store(&bug, b); race_ns = window_ns; }
int  buffer_bug(void) { return atomic_load(&bug); }
int  buffer_mutex_on(void) { return atomic_load(&bug) != BUG_NO_MUTEX; }
int  buffer_holder_blocked(void) { return atomic_load(&holder_blocked); }

/* "order" experiment: wait on a semaphore while holding the mutex */
static int wait_or_stop(sem_t *s);
static int wait_holding_lock(sem_t *s)
{
    atomic_fetch_add(&holder_blocked, 1);
    int r = wait_or_stop(s);
    atomic_fetch_sub(&holder_blocked, 1);
    return r;
}

static void deadline(struct timespec *ts, long ms)
{
    clock_gettime(CLOCK_REALTIME, ts);
    ts->tv_nsec += ms * 1000000L;
    if (ts->tv_nsec >= 1000000000L) { ts->tv_sec++; ts->tv_nsec -= 1000000000L; }
}

/* sem_wait that gives up when the simulation is stopped (so threads can exit
   cleanly instead of being killed while blocked) */
static int wait_or_stop(sem_t *s)
{
    struct timespec ts;
    sim_waiting(WAIT_SEM);
    while (sim_running()) {
        deadline(&ts, 50);
        if (sem_timedwait(s, &ts) == 0) { sim_waiting(WAIT_NONE); return 0; }
        if (errno != ETIMEDOUT && errno != EINTR) break;
    }
    sim_waiting(WAIT_NONE);
    return -1;
}

/* pthread_mutex_lock that also gives up on stop (needed for the deadlock experiment) */
static int lock(void)
{
    if (atomic_load(&bug) == BUG_NO_MUTEX) return 0;
    struct timespec ts;
    sim_waiting(WAIT_LOCK);
    while (sim_running()) {
        deadline(&ts, 50);
        int r = pthread_mutex_timedlock(&mutex, &ts);
        if (r == 0) { sim_waiting(WAIT_NONE); sim_lock_owner(1); return 0; }
        if (r != ETIMEDOUT) break;
    }
    sim_waiting(WAIT_NONE);
    return -1;
}

static void unlock(void)
{
    if (atomic_load(&bug) == BUG_NO_MUTEX) return;
    sim_lock_owner(0);
    pthread_mutex_unlock(&mutex);
}

/* without the mutex another thread may run between "read the index" and "write it back";
   a short pause makes that (normally rare) interleaving easy to see */
static void preempt(void)
{
    if (atomic_load(&bug) != BUG_NO_MUTEX || race_ns <= 0) return;
    struct timespec ts = { race_ns / 1000000000L, race_ns % 1000000000L };
    nanosleep(&ts, NULL);
}

int buffer_init(int n)
{
    size = n <= 0 ? BUFFER_SIZE : n;
    if (size > BUFFER_MAX) return -1;
    in = out = count = 0; last = -1;
    for (int i = 0; i < BUFFER_MAX; i++) atomic_store(&occ[i], 0);
    if (pthread_mutex_init(&mutex, NULL) != 0) return -1;
    if (sem_init(&empty, 0, size) != 0) return -1;
    if (sem_init(&full, 0, 0) != 0) return -1;
    return 0;
}

void buffer_destroy(void)
{
    pthread_mutex_destroy(&mutex);
    sem_destroy(&empty);
    sem_destroy(&full);
}

int insert_item(buffer_item item)
{
    int b = atomic_load(&bug);
    if (b == BUG_ORDER) {                     /* WRONG: lock first, then wait(empty) */
        if (lock() != 0) return -1;
        if (wait_holding_lock(&empty) != 0) { unlock(); return -1; }
    } else {
        if (b != BUG_NO_EMPTY && wait_or_stop(&empty) != 0)   /* wait(empty) */
            return -1;
        if (lock() != 0) return -1;           /* wait(mutex) — critical section */
    }
    atomic_store(&mutex_busy, 1);
    if (b == BUG_NONE && count >= size) {     /* must never happen */
        atomic_store(&mutex_busy, 0);
        unlock();
        sem_post(&empty);
        return -1;
    }
    int slot = in;                            /* read the shared index ...           */
    preempt();
    buffer[slot] = item;
    in = (slot + 1) % size;                   /* ... and write it back (lost update!) */
    int c = count;
    preempt();
    count = c + 1;
    last = slot;
    int err = atomic_exchange(&occ[slot], 1) ? RACE_OVERWRITE : 0;   /* slot still held an item */
    sim_on_insert(item, slot, count, err);    /* logging, still inside the lock */
    atomic_store(&mutex_busy, 0);
    unlock();                                 /* signal(mutex) */
    sem_post(&full);                          /* signal(full) */
    return 0;
}

int remove_item(buffer_item *item)
{
    if (item == NULL) return -1;
    int b = atomic_load(&bug);
    if (b == BUG_ORDER) {                     /* WRONG: lock first, then wait(full) */
        if (lock() != 0) return -1;
        if (wait_holding_lock(&full) != 0) { unlock(); return -1; }
    } else {
        if (b != BUG_NO_FULL && wait_or_stop(&full) != 0)     /* wait(full) */
            return -1;
        if (lock() != 0) return -1;
    }
    atomic_store(&mutex_busy, 1);
    if (b == BUG_NONE && count <= 0) {        /* must never happen */
        atomic_store(&mutex_busy, 0);
        unlock();
        sem_post(&full);
        return -1;
    }
    int slot = out;
    preempt();
    *item = buffer[slot];
    out = (slot + 1) % size;
    int c = count;
    preempt();
    count = c - 1;
    last = slot;
    int err = atomic_exchange(&occ[slot], 0) ? 0 : RACE_EMPTY_READ;  /* slot held no item */
    sim_on_remove(*item, slot, count, err);
    atomic_store(&mutex_busy, 0);
    unlock();
    sem_post(&empty);                         /* signal(empty) */
    return 0;
}

int buffer_capacity(void) { return size; }

int buffer_count(void)                        /* items really in the buffer */
{
    int c = 0;
    for (int i = 0; i < size; i++) c += atomic_load(&occ[i]);
    return c;
}

/* picture for the UI. Normally taken under the mutex; if the mutex is off or cannot be
   taken (the deadlock experiment holds it forever) the values are read as they are. */
void buffer_snapshot(int *slots, int *has, int *in_idx, int *out_idx, int *lst, int *cnt)
{
    struct timespec ts;
    deadline(&ts, 20);
    int locked = atomic_load(&bug) != BUG_NO_MUTEX && pthread_mutex_timedlock(&mutex, &ts) == 0;
    for (int i = 0; i < size; i++) {
        slots[i] = buffer[i];
        has[i] = atomic_load(&occ[i]);        /* slots that really hold an item */
    }
    *in_idx = in; *out_idx = out; *lst = last; *cnt = count;
    if (locked) pthread_mutex_unlock(&mutex);
}

void buffer_sem_values(int *empty_v, int *full_v)
{
    sem_getvalue(&empty, empty_v);
    sem_getvalue(&full, full_v);
}

int buffer_mutex_busy(void) { return atomic_load(&mutex_busy); }
