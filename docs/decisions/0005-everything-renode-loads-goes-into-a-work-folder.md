# Everything Renode loads goes into a work folder

2026-10-09

The Renode monitor breaks on paths with spaces (`D:\Embedded projects\...`). Each run copies the
firmware into a temp folder and starts Renode there, so monitor commands only see relative,
space-free paths. Paths inside the `.repl` file are quoted strings and may contain spaces.
