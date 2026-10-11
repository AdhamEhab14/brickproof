# Where BrickProof's evidence fits in the regulations

Two regulations ask, among much else, that a product can take a software update without being
left broken. A BrickProof report maps its results onto the clauses that say so.

**This is a map, not a verdict.** Whether a regulation is met is decided for a manufacturer's
whole process, by a type-approval authority (UN R156) or through the conformity assessment the
Cyber Resilience Act lays down. A tool run is one piece of evidence for one part of one clause.
Nothing here is legal advice.

## Sources

Read on 2026-10-11. The summaries below and in `src/brickproof/regulations.py` are paraphrases
written against these texts. The published wording is the one that counts.

| Regulation | Text |
|---|---|
| UN Regulation No. 156, Software update and software update management system | [UNECE, consolidated text](https://unece.org/sites/default/files/2024-03/R156e%20%282%29.pdf), paragraphs 7.2.1.1 and 7.2.2.1.1 to 7.2.2.1.3 |
| Regulation (EU) 2024/2847, Cyber Resilience Act | [Official Journal, EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202402847), Annex I, Part I point (2) and Part II |

## The clauses

| Clause | What it asks | What a passing run shows | What it does not show |
|---|---|---|---|
| UN R156 7.2.2.1.1 | After a failed or interrupted update, the vehicle can go back to the previous version, or reach a safe state | For one controller, every tested interruption by power loss ended with an approved image installed and running | Interruptions other than power loss; whether that is a "safe state" for the vehicle; other controllers in the same update |
| UN R156 7.2.1.1 | Authenticity and integrity of updates are protected; invalid updates are prevented | A half-written image is never left installed and running | That a forged or unsigned update is refused |
| UN R156 7.2.2.1.2 | An update only starts with enough power to finish it | Nothing directly: BrickProof covers the case this clause tries to avoid | The power check itself |
| CRA Annex I, Part I, (2)(h) | Essential functions stay available, also after an incident | A power failure during an update does not leave the device without working firmware | Other incidents; denial-of-service resistance |
| CRA Annex I, Part I, (2)(f) | Integrity of stored programs and configuration is protected; corruption is reported | An interrupted update does not leave corrupted code running as valid; an older image is not accepted again, where the adapter probes for it | Deliberate tampering; corruption reporting |
| CRA Annex I, Part II, (7) | Updates are distributed through secure mechanisms | The last step, installing on the device, survives power loss | Servers, transport, signing, timeliness |

## What a report says per clause

Each clause gets one of three marks, worked out from the run itself:

- **shown**: the run passed and has what that evidence rests on. The report adds the scope, for
  example "cut at 167 of its 167 distinct flash states, plus torn erases and programs (modelled),
  plus a further cut during recovery".
- **not shown**: the run failed, or the adapter has no oracle and the clause's evidence depends
  on checking the installed bytes.
- **not tested**: outside what a run can show (the power check of 7.2.2.1.2).

## Limits to keep in mind when using a report as evidence

- The device is emulated. The flash model follows the chip's rules (erase before program, write
  protection, option bytes), but torn-operation shapes are a model until compared with hardware.
- "Shown" is always for the states that were cut. A sampled plan says how many of how many.
- One update scenario per run: the images and the starting state named in the adapter.
