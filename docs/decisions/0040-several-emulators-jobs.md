# Several emulators (`--jobs`)

2026-10-11

Cuts are independent, each starts by restoring flash, so they can be shared out. `pool.py`
hands out work by index and releases results strictly in item order, so the tests run, their
order in the output and the place where `--fail-fast` stops are the same for any number of
emulators. Tested: one against four simulated devices give identical results for clean cuts,
torn states, depth, depth with torn, listed cuts and fail-fast.

- ports: `free_port()` never hands the same port out twice in a process;
- Renode processes start one at a time until their monitor answers, then work in parallel;
- a driver that signs its update at run time shares the prepared state with the other
  emulators (`export_state` / `import_state`), so all of them start the same update;
- depth exploration runs each level in three steps (trace all parents in parallel, decide in
  parent order which states are new, test those in parallel) to stay deterministic;
- `Golden.replay` is one per thread.

Full demo with `--torn --depth 2 -j 8`: 201 s for 747 runs, same counts as one emulator.

Torn states can now also be explored at depth (`depth: {torn: true}`): the half-done versions
of each recovery operation.
