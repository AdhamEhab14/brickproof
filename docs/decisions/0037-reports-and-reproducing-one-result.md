# Reports and reproducing one result

2026-10-11

A run has to leave evidence someone else can read and check.
- `--junit FILE`: one test case per result, class name by kind (baseline, cut, torn, depth-N),
  coverage and firmware hashes as properties. A failure carries its reason, where it cut and
  a command to reproduce it.
- `--html FILE`: one self-contained page (no outside resources, light and dark): verdict,
  a tile per kind, failures first with a reproduce command each, what was covered and what
  was sampled, how to read it and what is not modelled, the SHA-256 of every firmware file
  tested, then every run.
- Both are built from the same dictionary as the JSON report (`runner.as_dict`), so the three
  cannot disagree. It now also carries the start time, the tool version and the input hashes.
- `--cut N` (repeatable) runs only those operations and ignores the adapter's plan, torn and
  depth settings unless given again on the command line. It is what a report's reproduce
  command uses: `brickproof run adapter.yaml --cut 159`.

Left out on purpose: a mapping of results to regulation clauses (UN R156, CRA). The handoff
asks for one, with the clause wording verified first. Until someone has checked that wording
against the published texts, a report states what was tested and what was not, and no more.
