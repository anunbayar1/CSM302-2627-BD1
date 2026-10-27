/*
 * main.c — Producer–Consumer with Pthreads
 * OS Concepts (10th ed.), Chapter 7, Programming Project 4 (Figures 7.15, 7.16).
 *
 * usage: ./producer_consumer [-q] <sleep_seconds> <producers> <consumers> [max_nap_seconds]
 *   sleep_seconds    how long main() sleeps before terminating  (book parameter 1)
 *   producers        number of producer threads                 (book parameter 2)
 *   consumers        number of consumer threads                 (book parameter 3)
 *   max_nap_seconds  optional: longest random sleep of a thread (default 1.0)
 *   -q               only print the final summary
 */
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "buffer.h"
#include "sim.h"

#define MAX_THREADS 100

static atomic_int running = 1;
static int quiet = 0;
static double max_nap = 1.0;
static long produced = 0, consumed = 0;          /* changed only under the buffer mutex */
static struct timespec t0;
static pthread_mutex_t print_lock = PTHREAD_MUTEX_INITIALIZER;

int sim_running(void) { return atomic_load(&running); }

static double elapsed(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) / 1e9;
}

/* each thread keeps its own name so the log shows who did what */
static __thread char me[8] = "main";

void sim_on_insert(buffer_item item, int slot, int count)
{
    produced++;
    if (quiet) return;
    pthread_mutex_lock(&print_lock);
    printf("[%7.3fs] producer %-3s produced %2d -> slot %d   (buffer %d/%d)\n",
           elapsed(), me, item, slot, count, BUFFER_SIZE);
    pthread_mutex_unlock(&print_lock);
}

void sim_on_remove(buffer_item item, int slot, int count)
{
    consumed++;
    if (quiet) return;
    pthread_mutex_lock(&print_lock);
    printf("[%7.3fs] consumer %-3s consumed %2d <- slot %d   (buffer %d/%d)\n",
           elapsed(), me, item, slot, count, BUFFER_SIZE);
    pthread_mutex_unlock(&print_lock);
}

/* sleep a random time in [0, max_nap], waking early if the program is stopping */
static void nap(unsigned *seed)
{
    double total = max_nap * rand_r(seed) / (double)RAND_MAX;
    while (total > 0 && sim_running()) {
        double step = total < 0.05 ? total : 0.05;
        struct timespec ts = { (time_t)step, (long)((step - (time_t)step) * 1e9) };
        nanosleep(&ts, NULL);
        total -= step;
    }
}

typedef struct { int id; unsigned seed; } worker_arg;

static void *producer(void *param)                       /* Figure 7.16 */
{
    worker_arg *a = param;
    snprintf(me, sizeof me, "P%d", a->id);
    buffer_item item;
    while (sim_running()) {
        nap(&a->seed);                                   /* sleep for a random period */
        if (!sim_running()) break;
        item = rand_r(&a->seed) % 100;                   /* generate a random number  */
        if (insert_item(item) != 0) {
            if (sim_running()) fprintf(stderr, "%s: insert_item failed\n", me);
            break;
        }
    }
    return NULL;
}

static void *consumer(void *param)
{
    worker_arg *a = param;
    snprintf(me, sizeof me, "C%d", a->id);
    buffer_item item;
    while (sim_running()) {
        nap(&a->seed);
        if (!sim_running()) break;
        if (remove_item(&item) != 0) {
            if (sim_running()) fprintf(stderr, "%s: remove_item failed\n", me);
            break;
        }
    }
    return NULL;
}

static void usage(const char *prog)
{
    fprintf(stderr,
        "usage: %s [-q] <sleep_seconds> <producers> <consumers> [max_nap_seconds]\n"
        "  sleep_seconds    0 < x <= 3600\n"
        "  producers        1..%d\n"
        "  consumers        1..%d\n"
        "  max_nap_seconds  0..10 (default 1.0)\n"
        "  buffer size is BUFFER_SIZE = %d (change with: make BUFFER_SIZE=10)\n",
        prog, MAX_THREADS, MAX_THREADS, BUFFER_SIZE);
}

static int parse_long(const char *s, long lo, long hi, long *out)
{
    char *end; errno = 0;
    long v = strtol(s, &end, 10);
    if (errno || end == s || *end != '\0' || v < lo || v > hi) return -1;
    *out = v; return 0;
}

static int parse_double(const char *s, double lo, double hi, double *out)
{
    char *end; errno = 0;
    double v = strtod(s, &end);
    if (errno || end == s || *end != '\0' || !(v >= lo && v <= hi)) return -1;
    *out = v; return 0;
}

int main(int argc, char *argv[])
{
    /* 1. Get command line arguments */
    int a = 1;
    if (argc > 1 && strcmp(argv[1], "-q") == 0) { quiet = 1; a = 2; }
    int n = argc - a;
    if (n < 3 || n > 4) { usage(argv[0]); return 1; }

    double run_s; long np, nc;
    if (parse_double(argv[a], 0.001, 3600, &run_s) != 0) {
        fprintf(stderr, "error: sleep_seconds must be a number in (0, 3600], got '%s'\n", argv[a]);
        usage(argv[0]); return 1;
    }
    if (parse_long(argv[a + 1], 1, MAX_THREADS, &np) != 0) {
        fprintf(stderr, "error: producers must be an integer 1..%d, got '%s'\n", MAX_THREADS, argv[a + 1]);
        usage(argv[0]); return 1;
    }
    if (parse_long(argv[a + 2], 1, MAX_THREADS, &nc) != 0) {
        fprintf(stderr, "error: consumers must be an integer 1..%d, got '%s'\n", MAX_THREADS, argv[a + 2]);
        usage(argv[0]); return 1;
    }
    if (n == 4 && parse_double(argv[a + 3], 0, 10, &max_nap) != 0) {
        fprintf(stderr, "error: max_nap_seconds must be a number 0..10, got '%s'\n", argv[a + 3]);
        usage(argv[0]); return 1;
    }

    /* 2. Initialize buffer */
    if (buffer_init() != 0) { perror("buffer_init"); return 1; }
    clock_gettime(CLOCK_MONOTONIC, &t0);
    printf("BUFFER_SIZE=%d producers=%ld consumers=%ld run=%.2fs max_nap=%.2fs\n",
           BUFFER_SIZE, np, nc, run_s, max_nap);

    /* 3. Create producer thread(s)   4. Create consumer thread(s) */
    pthread_t tid[2 * MAX_THREADS];
    worker_arg args[2 * MAX_THREADS];
    unsigned base = (unsigned)time(NULL);
    int made = 0;
    for (long i = 0; i < np + nc; i++) {
        int is_prod = i < np;
        args[i].id = (int)(is_prod ? i + 1 : i - np + 1);
        args[i].seed = base ^ (unsigned)(i * 2654435761u);
        if (pthread_create(&tid[i], NULL, is_prod ? producer : consumer, &args[i]) != 0) {
            perror("pthread_create");
            break;
        }
        made++;
    }

    /* 5. Sleep */
    struct timespec ts = { (time_t)run_s, (long)((run_s - (time_t)run_s) * 1e9) };
    while (nanosleep(&ts, &ts) == -1 && errno == EINTR) {}

    /* 6. Exit — stop the threads, wait for them, then check that nothing was lost */
    atomic_store(&running, 0);
    for (int i = 0; i < made; i++) pthread_join(tid[i], NULL);

    int left = buffer_count();
    int ok = produced - consumed == left;
    printf("\nproduced=%ld consumed=%ld in_buffer=%d -> %s\n",
           produced, consumed, left, ok ? "CONSISTENT" : "INCONSISTENT");
    buffer_destroy();
    return ok ? 0 : 2;
}
