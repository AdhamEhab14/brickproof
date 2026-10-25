# Demo results (local, Windows 11, Renode 1.17.0)

2026-10-10

| Build | Result | First failing cut |
|---|---|---|
| correct | 168/168 cuts recovered, 18 min | none |
| `bug-consume_first` | caught | op 7: floor already raised to 2, staged v2 marked used, v1 refused: no bootable image |
| `bug-trust_header` | caught | op 15: half-written header trusted, CPU locks up |
| `bug-naive_floor` | caught | op 158: floor page erased, not yet rewritten; v1 accepted again |

168 is exactly the count the code predicts: floor record 7, Slot A erase 1, body 150,
header 8, consume 2.
