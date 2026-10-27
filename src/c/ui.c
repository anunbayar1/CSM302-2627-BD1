/*
 * ui.c — the same producer/consumer threads, driven by the web UI (src/gui.py).
 *
 *   ./producer_consumer --ui <size> <producers> <consumers> <prod_sleep> <cons_sleep> <speed> <paused>
 *
 * stdout (one line each, flushed):
 *   E I <who> <slot> <item> <t> <count>   insert_item() just happened (E R ... for remove_item)
 *   S {json}                        a state snapshot, every 50 ms
 *   END                             all threads have been joined
 * stdin  (one command per line):
 *   pause | resume | step | stop | tune <prod_sleep|-> <cons_sleep|-> <speed|->
 *
 * The threads, semaphores and mutex are exactly the ones in buffer.c; this file
 * only adds pause/step, live speed changes and the printing.
 */
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <semaphore.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "buffer.h"
#include "sim.h"

#define HOLD 0.3      /* seconds the "producing" / "consuming" state stays visible */

enum { ST_IDLE, ST_SLEEP, ST_PRODUCE, ST_WAIT, ST_CONSUME, ST_PAUSED, ST_STOPPED };
static const char *ST_NAME[] = {"idle", "sleeping", "producing", "waiting", "consuming", "paused", "stopped"};

static int np, nc;
static double prod_sleep, cons_sleep, speed = 1.0;
static pthread_mutex_t prm = PTHREAD_MUTEX_INITIALIZER;   /* guards the three numbers above */
static atomic_int paused = 0;
static sem_t step_sem;
static atomic_int state[2 * MAX_THREADS];
static pthread_mutex_t out_lock = PTHREAD_MUTEX_INITIALIZER;
static double stopped_at = -1;
static _Thread_local int my_idx;

static void get_params(double *ps, double *cs, double *sp)
{
    pthread_mutex_lock(&prm);
    if (ps) *ps = prod_sleep;
    if (cs) *cs = cons_sleep;
    if (sp) *sp = speed;
    pthread_mutex_unlock(&prm);
}

static void set_state(int st) { atomic_store(&state[my_idx], st); }

static void line(const char *s)
{
    pthread_mutex_lock(&out_lock);
    fputs(s, stdout);
    fflush(stdout);
    pthread_mutex_unlock(&out_lock);
}

void ui_on_insert(buffer_item item, int slot, int count)
{
    char b[96];
    snprintf(b, sizeof b, "E I %s %d %d %.3f %d\n", me, slot, item, elapsed(), count);
    line(b);
}

void ui_on_remove(buffer_item item, int slot, int count)
{
    char b[96];
    snprintf(b, sizeof b, "E R %s %d %d %.3f %d\n", me, slot, item, elapsed(), count);
    line(b);
}

/* sleep `t` simulated seconds; `which` = 1/2 caps the rest by the current
   producer/consumer sleep so tuning applies at once. Returns 0 if stopped. */
static int sim_sleep(double t, int which)
{
    struct timespec a, b;
    clock_gettime(CLOCK_MONOTONIC, &a);
    while (t > 0) {
        if (!sim_running()) return 0;
        double ps, cs, sp;
        get_params(&ps, &cs, &sp);
        double w = fmin(t / sp, 0.05);
        struct timespec ts = { (time_t)w, (long)((w - (time_t)w) * 1e9) };
        nanosleep(&ts, NULL);
        clock_gettime(CLOCK_MONOTONIC, &b);
        t -= ((b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) / 1e9) * sp;
        a = b;
        if (which == 1) t = fmin(t, ps);
        if (which == 2) t = fmin(t, cs);
    }
    return sim_running();
}

/* gate for Pause / Step; returns 0 if stopped */
static int checkpoint(void)
{
    if (!atomic_load(&paused)) return sim_running();
    set_state(ST_PAUSED);
    while (sim_running()) {
        if (!atomic_load(&paused) || sem_trywait(&step_sem) == 0) return 1;
        struct timespec ts = {0, 10 * 1000000L};
        nanosleep(&ts, NULL);
    }
    return 0;
}

typedef struct { int idx; unsigned seed; } warg;

static void *producer(void *p)
{
    warg *w = p; my_idx = w->idx;
    snprintf(me, sizeof me, "P%d", w->idx + 1);
    while (sim_running()) {
        double ps; get_params(&ps, NULL, NULL);
        set_state(ST_SLEEP);
        if (!sim_sleep(ps * rand_r(&w->seed) / (double)RAND_MAX, 1)) break;
        buffer_item item = rand_r(&w->seed) % 99 + 1;
        set_state(ST_PRODUCE);
        if (!sim_sleep(HOLD, 0) || !checkpoint()) break;
        set_state(ST_WAIT);
        if (insert_item(item) != 0) break;
    }
    set_state(ST_STOPPED);
    return NULL;
}

static void *consumer(void *p)
{
    warg *w = p; my_idx = w->idx;
    snprintf(me, sizeof me, "C%d", w->idx - np + 1);
    buffer_item item;
    while (sim_running()) {
        double cs; get_params(NULL, &cs, NULL);
        set_state(ST_SLEEP);
        if (!sim_sleep(cs * rand_r(&w->seed) / (double)RAND_MAX, 2)) break;
        if (!checkpoint()) break;
        set_state(ST_WAIT);
        if (remove_item(&item) != 0) break;
        set_state(ST_CONSUME);
        if (!sim_sleep(HOLD, 0)) break;
    }
    set_state(ST_STOPPED);
    return NULL;
}

static void snapshot(int stopped)
{
    int slots[BUFFER_MAX], has[BUFFER_MAX], in, out, last, cnt, ev, fv;
    int busy = buffer_mutex_busy();
    buffer_snapshot(slots, has, &in, &out, &last, &cnt);
    buffer_sem_values(&ev, &fv);
    double ps, cs, sp;
    get_params(&ps, &cs, &sp);
    int n = buffer_capacity();

    char b[8192];
    int k = snprintf(b, sizeof b, "S {\"engine\":\"c\",\"slots\":[");
    for (int i = 0; i < n; i++)
        k += has[i] ? snprintf(b + k, sizeof b - k, "%s%d", i ? "," : "", slots[i])
                    : snprintf(b + k, sizeof b - k, "%snull", i ? "," : "");
    k += snprintf(b + k, sizeof b - k, "],\"in_idx\":%d,\"out_idx\":%d,\"last\":", in, out);
    k += last < 0 ? snprintf(b + k, sizeof b - k, "null") : snprintf(b + k, sizeof b - k, "%d", last);
    k += snprintf(b + k, sizeof b - k, ",\"empty\":%d,\"full\":%d,\"mutex_locked\":%s,\"states\":{",
                  ev, fv, busy ? "true" : "false");
    for (int i = 0; i < np + nc; i++)
        k += snprintf(b + k, sizeof b - k, "%s\"%c%d\":\"%s\"", i ? "," : "",
                      i < np ? 'P' : 'C', i < np ? i + 1 : i - np + 1, ST_NAME[atomic_load(&state[i])]);
    double el = stopped && stopped_at >= 0 ? stopped_at : elapsed();
    snprintf(b + k, sizeof b - k,
             "},\"produced\":%ld,\"consumed\":%ld,\"paused\":%s,\"stopped\":%s,"
             "\"speed\":%g,\"prod_sleep\":%g,\"cons_sleep\":%g,\"elapsed\":%.2f}\n",
             (long)atomic_load(&produced), (long)atomic_load(&consumed),
             atomic_load(&paused) ? "true" : "false", stopped ? "true" : "false", sp, ps, cs, el);
    line(b);
}

static void *reporter(void *unused)
{
    (void)unused;
    while (sim_running()) {
        snapshot(0);
        struct timespec ts = {0, 50 * 1000000L};
        nanosleep(&ts, NULL);
    }
    return NULL;
}

static int num(const char *s, double lo, double hi, double *out)
{
    char *end; errno = 0;
    double v = strtod(s, &end);
    if (errno || end == s || *end != '\0' || !(v >= lo && v <= hi)) return -1;
    *out = v; return 0;
}

static void tune(char *args)
{
    char a[32] = "-", b[32] = "-", c[32] = "-";
    sscanf(args, "%31s %31s %31s", a, b, c);
    double ps, cs, sp;
    get_params(&ps, &cs, &sp);
    if ((strcmp(a, "-") && num(a, 0, 10, &ps)) || (strcmp(b, "-") && num(b, 0, 10, &cs)) ||
        (strcmp(c, "-") && num(c, 0.25, 4, &sp))) {
        fprintf(stderr, "ERR bad tune: %s\n", args);
        return;
    }
    pthread_mutex_lock(&prm);
    prod_sleep = ps; cons_sleep = cs; speed = sp;
    pthread_mutex_unlock(&prm);
}

int ui_main(int argc, char *argv[])
{
    double size, p, c, ps, cs, sp, pa;
    if (argc != 7 || num(argv[0], 1, BUFFER_MAX, &size) || num(argv[1], 1, MAX_THREADS, &p) ||
        num(argv[2], 1, MAX_THREADS, &c) || num(argv[3], 0, 10, &ps) || num(argv[4], 0, 10, &cs) ||
        num(argv[5], 0.25, 4, &sp) || num(argv[6], 0, 1, &pa)) {
        fprintf(stderr, "usage: --ui <size 1..%d> <producers> <consumers> <prod_sleep> "
                        "<cons_sleep> <speed 0.25..4> <paused 0|1>\n", BUFFER_MAX);
        return 1;
    }
    np = (int)p; nc = (int)c; prod_sleep = ps; cons_sleep = cs; speed = sp;
    atomic_store(&paused, pa != 0);
    if (buffer_init((int)size) != 0 || sem_init(&step_sem, 0, 0) != 0) {
        fprintf(stderr, "ERR init failed\n");
        return 1;
    }

    pthread_t tid[2 * MAX_THREADS], rep;
    warg args[2 * MAX_THREADS];
    unsigned base = (unsigned)time(NULL);
    int made = 0;
    for (int i = 0; i < np + nc; i++) atomic_store(&state[i], ST_IDLE);
    for (int i = 0; i < np + nc; i++) {
        args[i].idx = i;
        args[i].seed = base ^ (unsigned)(i * 2654435761u);
        if (pthread_create(&tid[i], NULL, i < np ? producer : consumer, &args[i]) != 0) break;
        made++;
    }
    pthread_create(&rep, NULL, reporter, NULL);

    char cmd[128];
    while (fgets(cmd, sizeof cmd, stdin)) {          /* EOF (parent gone) also stops */
        cmd[strcspn(cmd, "\r\n")] = '\0';
        if (!strcmp(cmd, "pause")) atomic_store(&paused, 1);
        else if (!strcmp(cmd, "resume")) atomic_store(&paused, 0);
        else if (!strcmp(cmd, "step")) { atomic_store(&paused, 1); sem_post(&step_sem); }
        else if (!strncmp(cmd, "tune ", 5)) tune(cmd + 5);
        else if (!strcmp(cmd, "stop")) break;
        else if (cmd[0]) fprintf(stderr, "ERR unknown command: %s\n", cmd);
    }

    stopped_at = elapsed();
    atomic_store(&running, 0);
    for (int i = 0; i < made; i++) pthread_join(tid[i], NULL);
    pthread_join(rep, NULL);
    snapshot(1);
    line("END\n");
    buffer_destroy();
    sem_destroy(&step_sem);
    return 0;
}
