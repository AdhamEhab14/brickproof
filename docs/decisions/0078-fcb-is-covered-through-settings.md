# FCB is covered through settings

2026-10-16

The plan lists FCB and settings as separate adapters. FCB is a log, not a key-value store, so
running the storage workload on it directly would need a compaction layer written for the
purpose, which is what Zephyr's settings FCB backend already is. The settings-on-FCB adapter
exercises FCB's append, CRC, sector rotation and init under every cut, and found both FCB
problems (zephyrproject-rtos/zephyr#122446 and the addition to #121749). A second adapter with
our own compaction would mostly test that compaction, so there is none.
