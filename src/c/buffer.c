/*
 * buffer.c — bounded buffer for the producer–consumer problem
 * (OS Concepts, Section 7.1.1, Figures 7.1, 7.2 and 7.14).
 *
 *   empty : counting semaphore, number of empty slots   (starts at BUFFER_SIZE)
 *   full  : counting semaphore, number of full slots    (starts at 0)
 *   mutex : pthread mutex lock protecting the circular queue itself
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
static buffer_item buffer[BUFFER_SIZE];
static int in = 0, out = 0, count = 0;

static pthread_mutex_t mutex;
static sem_t empty;
static sem_t full;

int buffer_init(void)
{
    if (pthread_mutex_init(&mutex, NULL) != 0) return -1;
    if (sem_init(&empty, 0, BUFFER_SIZE) != 0) return -1;
    if (sem_init(&full, 0, 0) != 0) return -1;
    return 0;
}

void buffer_destroy(void)
{
    pthread_mutex_destroy(&mutex);
    sem_destroy(&empty);
    sem_destroy(&full);
}

/* sem_wait that gives up when the simulation is stopped (so threads can exit
   cleanly instead of being killed while blocked) */
static int wait_or_stop(sem_t *s)
{
    struct timespec ts;
    while (sim_running()) {
        clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_nsec += 50 * 1000000L;                     /* 50 ms */
        if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
        if (sem_timedwait(s, &ts) == 0) return 0;
        if (errno != ETIMEDOUT && errno != EINTR) return -1;
    }
    return -1;
}

int insert_item(buffer_item item)
{
    if (wait_or_stop(&empty) != 0)            /* wait(empty) */
        return -1;
    pthread_mutex_lock(&mutex);               /* wait(mutex) — critical section */
    if (count >= BUFFER_SIZE) {               /* must never happen */
        pthread_mutex_unlock(&mutex);
        sem_post(&empty);
        return -1;
    }
    int slot = in;
    buffer[in] = item;
    in = (in + 1) % BUFFER_SIZE;
    count++;
    sim_on_insert(item, slot, count);         /* logging, still inside the lock */
    pthread_mutex_unlock(&mutex);             /* signal(mutex) */
    sem_post(&full);                          /* signal(full) */
    return 0;
}

int remove_item(buffer_item *item)
{
    if (item == NULL) return -1;
    if (wait_or_stop(&full) != 0)             /* wait(full) */
        return -1;
    pthread_mutex_lock(&mutex);
    if (count <= 0) {                         /* must never happen */
        pthread_mutex_unlock(&mutex);
        sem_post(&full);
        return -1;
    }
    int slot = out;
    *item = buffer[out];
    out = (out + 1) % BUFFER_SIZE;
    count--;
    sim_on_remove(*item, slot, count);
    pthread_mutex_unlock(&mutex);
    sem_post(&empty);                         /* signal(empty) */
    return 0;
}

int buffer_count(void)
{
    pthread_mutex_lock(&mutex);
    int c = count;
    pthread_mutex_unlock(&mutex);
    return c;
}
