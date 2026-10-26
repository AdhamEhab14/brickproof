# BrickProof documentation

**Start here**

- [Getting started](getting-started.md): install, the bundled demo, its bug builds, the five chips
- [Testing your own firmware](guide/testing-your-firmware.md): `init`, `check`, `run --full`, and the three kinds of update
- Five steps for your kind of update: [MCUboot](guide/mcuboot.md), [a bootloader that installs a staged image](guide/staged-update.md), [an update sent over the UART](guide/uart-protocol.md), [a flash storage library](guide/storage-library.md)

**Using it**

- [What a run covers](guide/what-a-run-covers.md): clean cuts, torn writes, a second cut during recovery, damaged images, worn pages, bit errors, a broken link, the chip's rules, the outside judge
- [Results, a real board, and CI](guide/results-and-ci.md): the reports, exporting a cut's flash for a board, the GitHub Action, Docker

**Reference**

- [The adapter file](reference/adapter.md): every key
- [Command-line options](reference/cli.md) and exit codes
- [Limits](reference/limits.md): what is modelled and what is not
- [Regulations](regulations.md): how a report maps to UN R156 and the EU Cyber Resilience Act

**The project**

- [Targets](../adapters/README.md): the real firmware BrickProof has been run on, and what it found
- [How BrickProof is built](architecture.md): where the code is
- [Features and what proves them](features.md), and the parity check that keeps every result the same through a change
- [Decisions](decisions/README.md): why things are the way they are, with the measurements
- [Releasing](releasing.md), [future work](future-work.md)
