"""Several emulators working through one list of tests.

Cuts are independent: each starts by restoring flash. So they can be spread over as
many emulators as the machine has cores for. What must not change with the number of
workers is the result: the same tests, reported in the same order, stopping at the
same place. The pool hands out work by index and releases results strictly in order,
whatever order they finish in.
"""
import threading


class Pool:
    """workers: a list of (session, driver) pairs, each its own emulator."""

    def __init__(self, workers):
        self.workers = list(workers)

    def __len__(self):
        return len(self.workers)

    @property
    def first(self):
        return self.workers[0]

    def run(self, fn, items, on_result=None, stop=None):
        """fn(session, driver, item) for every item. Returns the results in item order.

        fn may return one result or a list of them. on_result sees each in order.
        If stop(result) is true for one, nothing after it is kept or reported, exactly
        as if the items had been run one at a time. An exception in any worker stops
        the rest and is raised here."""
        items = list(items)
        if not items:
            return []
        done = {}                       # index -> list of results, finished but not released
        out = []
        state = {"next": 0, "release": 0, "stopped": False, "error": None}
        lock = threading.Lock()

        def release():
            # called with the lock held: hand over everything that is next in line
            while state["release"] in done and not state["stopped"]:
                for r in done.pop(state["release"]):
                    out.append(r)
                    if on_result:
                        on_result(r)
                    if stop and stop(r):
                        state["stopped"] = True
                        return
                state["release"] += 1

        def work(session, driver):
            while True:
                with lock:
                    if state["stopped"] or state["error"] or state["next"] >= len(items):
                        return
                    i = state["next"]
                    state["next"] += 1
                try:
                    r = fn(session, driver, items[i])
                except BaseException as e:      # noqa: B036 - re-raised in the caller's thread
                    with lock:
                        state["error"] = state["error"] or e
                    return
                with lock:
                    done[i] = r if isinstance(r, list) else [r]
                    release()

        if len(self.workers) == 1:
            work(*self.workers[0])              # same code path, no thread: plain tracebacks
        else:
            threads = [threading.Thread(target=work, args=w, daemon=True) for w in self.workers]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        if state["error"]:
            raise state["error"]
        return out
