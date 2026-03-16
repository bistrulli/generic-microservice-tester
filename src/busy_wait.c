/**
 * busy_wait.c — GIL-releasing CPU busy-wait for LQN activity simulation.
 *
 * Called via ctypes from Python. When ctypes invokes a C function, the GIL
 * is released automatically, enabling true parallel CPU work across threads
 * (required for LQN AND-fork semantics).
 *
 * Uses CLOCK_THREAD_CPUTIME_ID for per-thread CPU time measurement, so each
 * thread in a ThreadPoolExecutor gets accurate, independent timing.
 *
 * Build:
 *   Linux:  gcc -shared -fPIC -O2 -o busy_wait.so busy_wait.c
 *   macOS:  gcc -shared -fPIC -O2 -o busy_wait.so busy_wait.c
 */

#include <time.h>

void busy_wait_cpu(double seconds) {
    if (seconds <= 0.0) {
        return;
    }

    struct timespec start, now;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &start);

    double elapsed = 0.0;
    while (elapsed < seconds) {
        clock_gettime(CLOCK_THREAD_CPUTIME_ID, &now);
        elapsed = (double)(now.tv_sec - start.tv_sec)
                + (double)(now.tv_nsec - start.tv_nsec) / 1e9;
    }
}
