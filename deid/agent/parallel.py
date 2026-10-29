"""Run model calls for several notes at once without changing what comes out.

    stopped = run_ordered(work, items, workers, stop, consume)

work(item) runs on a worker thread; consume(result) runs on the calling thread, one
result at a time, in the order of items, so anything that adds up usage, writes
progress or builds a list behaves as it did when the calls ran one after another.
stop() is checked before each item is handed out; with workers = 1 the loop is the
plain sequential one. Results already in flight when stop() turns true are still
consumed, so a token cap can be passed by the calls that were already running (at
most 2 x workers notes), never by more.
"""

from collections import deque
from concurrent.futures import ThreadPoolExecutor

DONE = object()


def run_ordered(work, items, workers, stop, consume):
    """-> True when stop() ended the run before every item was handed out."""
    if workers <= 1:
        for item in items:
            if stop():
                return True
            consume(work(item))
        return False
    stopped, pending, queue = False, deque(), iter(items)
    window = 2 * workers
    with ThreadPoolExecutor(max_workers=workers) as pool:
        def fill():
            nonlocal stopped
            while not stopped and len(pending) < window:
                item = next(queue, DONE)
                if item is DONE:
                    return
                if stop():
                    stopped = True
                    return
                pending.append(pool.submit(work, item))

        fill()
        while pending:
            consume(pending.popleft().result())
            fill()
    return stopped
