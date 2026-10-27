/*
 * main.c — Producer–Consumer with Pthreads
 * OS Concepts (10th ed.), Chapter 7, Programming Project 4 (Figures 7.15, 7.16).
 *
 * usage: ./producer_consumer [-q] [--bug KIND] <sleep_seconds> <producers> <consumers> [max_nap_seconds]
 *        ./producer_consumer --ui ...   (engine for the web UI, see ui.c)
 *   sleep_seconds    how long main() sleeps before terminating  (book parameter 1)
 *   producers        number of producer threads                 (book parameter 2)
 *   consumers        number of consumer threads                 (book parameter 3)
 *   max_nap_seconds  optional: longest random sleep of a thread (default 1.0)
 *   -q               only print the final summary
 *   --bug KIND       experiment with one classic mistake, the errors are reported:
 *                      no-mutex  no mutex lock          -> race condition (lost / garbage items)
 *                      no-empty  producer skips wait(empty) -> overflow (unread items overwritten)
 *                      no-full   consumer skips wait(full)  -> underflow (empty slots read)
 *                      order     wait(mutex) before wait(empty/full) -> deadlock
 *   --no-mutex       same as --bug no-mutex
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

atomic_int  running = 1;
atomic_long produced = 0, consumed = 0;          /* changed only under the buffer mutex */
atomic_long lost = 0, bad_reads = 0;
static atomic_long last_progress_ms = 0;          /* for the deadlock report */
static const char *BUG_NAMES[] = {"none", "no-mutex", "no-empty", "no-full", "order"};
_Thread_local char me[16] = "main";
static int quiet = 0;
static int ui_mode = 0;
static double max_nap = 1.0;
static struct timespec t0;
static int t0_set = 0;
static pthread_mutex_t print_lock = PTHREAD_MUTEX_INITIALIZER;

int sim_running(void) { return atomic_load(&running); }

double elapsed(void)
{
    struct timespec t;
    if (!t0_set) { clock_gettime(CLOCK_MONOTONIC, &t0); t0_set = 1; }
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) / 1e9;
}

void sim_waiting(int what) { if (ui_mode) ui_waiting(what); }
void sim_lock_owner(int has) { if (ui_mode) ui_lock_owner(has); }

static void progress(void) { atomic_store(&last_progress_ms, (long)(elapsed() * 1000)); }

static const char *race_text(int err)
{
    return err == RACE_OVERWRITE ? "   !! slot was still full -> an item is lost"
         : err == RACE_EMPTY_READ ? "   !! slot was empty -> read garbage" : "";
}

void sim_on_insert(buffer_item item, int slot, int count, int err)
{
    atomic_fetch_add(&produced, 1);
    progress();
    if (err) atomic_fetch_add(&lost, 1);
    if (ui_mode) { ui_on_insert(item, slot, count, err); return; }
    if (quiet) return;
    pthread_mutex_lock(&print_lock);
    printf("[%7.3fs] producer %-3s produced %2d -> slot %d   (buffer %d/%d)%s\n",
           elapsed(), me, item, slot, count, buffer_capacity(), race_text(err));
    pthread_mutex_unlock(&print_lock);
}

void sim_on_remove(buffer_item item, int slot, int count, int err)
{
    atomic_fetch_add(&consumed, 1);
    progress();
    if (err) atomic_fetch_add(&bad_reads, 1);
    if (ui_mode) { ui_on_remove(item, slot, count, err); return; }
    if (quiet) return;
    pthread_mutex_lock(&print_lock);
    printf("[%7.3fs] consumer %-3s consumed %2d <- slot %d   (buffer %d/%d)%s\n",
           elapsed(), me, item, slot, count, buffer_capacity(), race_text(err));
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
        "usage: %s [-q] [--bug KIND] <sleep_seconds> <producers> <consumers> [max_nap_seconds]\n"
        "  sleep_seconds    0 < x <= 3600\n"
        "  producers        1..%d\n"
        "  consumers        1..%d\n"
        "  max_nap_seconds  0..10 (default 1.0)\n"
        "  --bug KIND       experiment: no-mutex | no-empty | no-full | order (deadlock)\n"
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
    if (argc > 1 && strcmp(argv[1], "--ui") == 0) {   /* engine for the web UI */
        ui_mode = 1;
        clock_gettime(CLOCK_MONOTONIC, &t0); t0_set = 1;
        return ui_main(argc - 2, argv + 2);
    }

    /* 1. Get command line arguments */
    int a = 1, bug = BUG_NONE;
    for (; a < argc; a++) {
        if (strcmp(argv[a], "-q") == 0) quiet = 1;
        else if (strcmp(argv[a], "--no-mutex") == 0) bug = BUG_NO_MUTEX;
        else if (strcmp(argv[a], "--bug") == 0 && a + 1 < argc) {
            int k = -1;
            for (int i = 0; i < 5; i++) if (strcmp(argv[a + 1], BUG_NAMES[i]) == 0) k = i;
            if (k < 0) { fprintf(stderr, "error: unknown --bug '%s'\n", argv[a + 1]); usage(argv[0]); return 1; }
            bug = k; a++;
        }
        else break;
    }
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
    if (buffer_init(BUFFER_SIZE) != 0) { perror("buffer_init"); return 1; }
    buffer_set_bug(bug, 100 * 1000L);            /* without the mutex: 0.1 ms pause in the critical section */
    clock_gettime(CLOCK_MONOTONIC, &t0); t0_set = 1;
    printf("BUFFER_SIZE=%d producers=%ld consumers=%ld run=%.2fs max_nap=%.2fs%s%s\n",
           BUFFER_SIZE, np, nc, run_s, max_nap, bug ? " bug=" : "", bug ? BUG_NAMES[bug] : "");

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
    double idle = elapsed() - atomic_load(&last_progress_ms) / 1000.0;
    int deadlock = buffer_holder_blocked() && idle > 0.3;
    atomic_store(&running, 0);
    for (int i = 0; i < made; i++) pthread_join(tid[i], NULL);

    int left = buffer_count();
    int ok = produced - consumed == left && lost == 0 && bad_reads == 0 && !deadlock;
    printf("\nproduced=%ld consumed=%ld in_buffer=%d -> %s\n",
           (long)produced, (long)consumed, left, deadlock ? "DEADLOCK" : ok ? "CONSISTENT" : "INCONSISTENT");
    if (deadlock)
        printf("DEADLOCK: no progress for the last %.1fs (a thread holds the mutex while it waits on a semaphore)\n", idle);
    else if (bug || !ok)
        printf("errors: lost_items=%ld bad_reads=%ld\n", (long)lost, (long)bad_reads);
    buffer_destroy();
    return deadlock ? 3 : ok ? 0 : 2;
}
