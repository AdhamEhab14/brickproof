# W1 cuts are real cuts only

2026-10-09

Cut positions are either `on_erase: <page>` or `at_op: N` (operation N counted from the start of
the update). No generated or torn states yet; those come with the cut planner (W3).

The W1 cut list stays inside the SBL phase on purpose. A cut *before* the SBL starts (ops 0 to 6:
the Boot Manager state page) should leave the old FBL running, but the driver's
`check_recovered()` asks for the new one (Slot B wiped). "Old or new image, both fine" is the
oracle's job (W4, invariant I1), not the driver's.
