# SARIF output (plan item 22)

2026-10-16

`--sarif FILE` writes the failures as SARIF 2.1.0, so a CI run's failures appear as code
scanning alerts next to the code. One result per failure; the rule is its kind (power cut,
torn state, cuts in a row, bad content, broken link, bit error, or the update failing with
no cut), so alerts group by what went wrong. The location is the adapter file, not the
firmware the plan named: code scanning needs a file in the repository, and the firmware is a
build output that is usually not committed, while the adapter always is. A stable
fingerprint (adapter name and result name) lets GitHub match an alert across runs. The
message carries the reproduce and export commands.

**Checked**: the SARIF from a run of the demo's consume_first bug (15 failures) validates
against the SARIF 2.1.0 schema from schemastore.org. Not checked yet: an upload to a
repository's code scanning (it needs code scanning turned on there).
