# Where a cut's time goes (profiled)

2026-10-10

Each `emulation RunFor` costs about 100 ms of wall time however short it is, plus about 37 ms
of UART polling after it. So the cost of a cut is the number of RunFor calls, not the amount
of emulated time. The demo made about 43 per cut; 40 of them were the rollback probe waiting
its whole 2 s timeout, in 0.05 s steps, for a banner that must not appear.

Fix: the probe waits for any image to announce itself, then checks which one it was.
Demo cut: 6.5 s -> about 1.9 s. Rule for new drivers: never wait for the absence of something
in small steps; wait for a positive event, then inspect.

Still to do: the one-off 128 KB flash dump (`sysbus ReadBytes`) takes 4.8 s of setup.
