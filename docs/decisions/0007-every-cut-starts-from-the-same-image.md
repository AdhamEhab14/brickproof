# Every cut starts from the same image

2026-10-09

After `prepare()` the engine dumps flash once. Each cut restores that image and power-cycles
before starting the update, so cuts are independent and can later run in parallel instances.
