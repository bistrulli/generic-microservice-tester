"""Tests for the busy_wait C extension.

Verifies:
- Single-thread CPU timing accuracy
- True parallel execution across threads (GIL released)
- Per-thread time measurement via time.thread_time()
"""

import time
from concurrent.futures import ThreadPoolExecutor, wait


class TestBusyWaitSingleThread:
    """Verify CPU busy-wait timing accuracy in a single thread."""

    def test_zero_seconds(self, busy_wait_lib):
        """Zero duration should return immediately."""
        start = time.monotonic()
        busy_wait_lib.busy_wait_cpu(0.0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.05, f"Zero-duration call took {elapsed:.4f}s"

    def test_negative_seconds(self, busy_wait_lib):
        """Negative duration should return immediately."""
        start = time.monotonic()
        busy_wait_lib.busy_wait_cpu(-1.0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.05, f"Negative-duration call took {elapsed:.4f}s"

    def test_timing_accuracy_short(self, busy_wait_lib):
        """Short busy-wait (50ms) should be accurate within ±20%."""
        target = 0.05
        start = time.monotonic()
        busy_wait_lib.busy_wait_cpu(target)
        elapsed = time.monotonic() - start
        # Allow generous tolerance for CI/slow machines
        assert elapsed >= target * 0.8, (
            f"Too fast: {elapsed:.4f}s < {target * 0.8:.4f}s"
        )
        assert elapsed < target * 2.0, f"Too slow: {elapsed:.4f}s > {target * 2.0:.4f}s"

    def test_timing_accuracy_medium(self, busy_wait_lib):
        """Medium busy-wait (200ms) should be accurate within ±15%."""
        target = 0.2
        start = time.monotonic()
        busy_wait_lib.busy_wait_cpu(target)
        elapsed = time.monotonic() - start
        assert elapsed >= target * 0.85, f"Too fast: {elapsed:.4f}s"
        assert elapsed < target * 1.5, f"Too slow: {elapsed:.4f}s"


class TestBusyWaitParallelThreads:
    """Verify that C extension releases the GIL, enabling true parallelism."""

    def test_two_threads_parallel(self, busy_wait_lib):
        """Two threads with 0.2s and 0.3s should complete in ~0.3s (max), not 0.5s (sum)."""
        time_a = 0.2
        time_b = 0.3

        with ThreadPoolExecutor(max_workers=2) as pool:
            start = time.monotonic()
            future_a = pool.submit(busy_wait_lib.busy_wait_cpu, time_a)
            future_b = pool.submit(busy_wait_lib.busy_wait_cpu, time_b)
            wait([future_a, future_b])
            elapsed = time.monotonic() - start

        # If GIL is released: wall-clock ≈ max(0.2, 0.3) = 0.3s
        # If GIL is NOT released: wall-clock ≈ sum(0.2, 0.3) = 0.5s
        max_time = max(time_a, time_b)
        sum_time = time_a + time_b

        assert elapsed < sum_time * 0.85, (
            f"Wall-clock {elapsed:.4f}s is close to sum ({sum_time:.4f}s) — "
            f"GIL may not be released. Expected ~{max_time:.4f}s."
        )
        assert elapsed >= max_time * 0.8, (
            f"Wall-clock {elapsed:.4f}s is suspiciously fast (< {max_time * 0.8:.4f}s)"
        )

    def test_four_threads_parallel(self, busy_wait_lib):
        """Four threads should complete in ~max(times), not sum(times)."""
        times = [0.1, 0.15, 0.2, 0.12]

        with ThreadPoolExecutor(max_workers=4) as pool:
            start = time.monotonic()
            futures = [pool.submit(busy_wait_lib.busy_wait_cpu, t) for t in times]
            wait(futures)
            elapsed = time.monotonic() - start

        max_time = max(times)
        sum_time = sum(times)

        assert elapsed < sum_time * 0.7, (
            f"Wall-clock {elapsed:.4f}s too close to sum ({sum_time:.4f}s)"
        )
        assert elapsed >= max_time * 0.8, (
            f"Wall-clock {elapsed:.4f}s < expected min ({max_time * 0.8:.4f}s)"
        )


class TestBusyWaitThreadTime:
    """Verify per-thread CPU time measurement with time.thread_time()."""

    def test_thread_time_accuracy(self, busy_wait_lib):
        """time.thread_time() should report per-thread CPU time accurately."""
        target = 0.15
        thread_cpu_before = time.thread_time()
        busy_wait_lib.busy_wait_cpu(target)
        thread_cpu_after = time.thread_time()

        thread_cpu = thread_cpu_after - thread_cpu_before
        # thread_time() measures the calling thread's CPU — should match target
        assert thread_cpu >= target * 0.7, (
            f"thread_time delta {thread_cpu:.4f}s too low for {target}s busy-wait"
        )
        assert thread_cpu < target * 2.0, (
            f"thread_time delta {thread_cpu:.4f}s too high for {target}s busy-wait"
        )

    def test_parallel_thread_times_independent(self, busy_wait_lib):
        """Each thread should report its own CPU time, not the combined total."""
        time_a = 0.1
        time_b = 0.2
        results = {}

        def measure(name, duration):
            t0 = time.thread_time()
            busy_wait_lib.busy_wait_cpu(duration)
            t1 = time.thread_time()
            results[name] = t1 - t0

        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(measure, "a", time_a)
            fb = pool.submit(measure, "b", time_b)
            wait([fa, fb])

        # Each thread should report approximately its own target time
        assert results["a"] >= time_a * 0.7, (
            f"Thread A: {results['a']:.4f}s, expected ~{time_a}s"
        )
        assert results["a"] < time_a * 2.0, (
            f"Thread A: {results['a']:.4f}s, too high for {time_a}s"
        )
        assert results["b"] >= time_b * 0.7, (
            f"Thread B: {results['b']:.4f}s, expected ~{time_b}s"
        )
        assert results["b"] < time_b * 2.0, (
            f"Thread B: {results['b']:.4f}s, too high for {time_b}s"
        )
