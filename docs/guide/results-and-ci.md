# Results, a real board, and CI

## The reports

The HTML report is one self-contained page: the verdict, what was covered and what was
sampled, each failure with a command that reproduces it and one that exports its flash
for a real board, the SHA-256 of every firmware file
tested, and where the evidence fits in UN R156 and the EU Cyber Resilience Act
([how that map is made](../regulations.md)).

To check a failure on a real board, export the flash that cut leaves and program it:

```bash
brickproof export my_adapter.yaml --cut 3232 -o op-3232.bin        # add --torn KIND for a torn state
```

It writes `op-3232.bin` (the chip's flash; option bytes and an external flash chip get files
of their own) and `op-3232.txt` with the ST-LINK or nrfjprog commands. The bytes are the ones
the run powered the emulator up from.

## In CI

```yaml
- uses: AdhamEhab14/brickproof@v0.3.0
  with:
    adapter: test/brickproof.yaml
    args: --torn --depth 2 -j 3
```

The job fails if any cut does not recover, and the JSON, JUnit and HTML reports are uploaded
as an artifact. With `sarif: "true"` (and `permissions: security-events: write` in the
workflow) each failure also shows up in the repository's code scanning alerts, with its
reproduce and export commands.

## Docker

```bash
docker run --rm ghcr.io/adhamehab14/brickproof              # the demo
docker run --rm -v "$PWD:/work" ghcr.io/adhamehab14/brickproof run adapter.yaml --html report.html
```

The image brings Renode, so it runs every chip but the STM32H563. m33mu is AGPL-3.0 and is
not shipped in it: build m33mu yourself (or use the GitHub Action, which builds it) for that one.
