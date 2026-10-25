# The ARM toolchain is cached in CI

2026-10-24

e2e on main was cancelled at its 60 minute limit three times in two days, every time
before BrickProof had run long enough to finish. The job installed the toolchain with
`apt-get install gcc-arm-none-eabi cmake ninja-build`, which with the recommended
packages is 588 MB from the Ubuntu mirror; on a slow evening that took 51 minutes at
193 kB/s, and the 55 results reached in the time left all passed.

The e2e job and the exhaustive workflow now use Arm's own GNU toolchain, the same GCC
(13.2.rel1) as Ubuntu's package, as one 179 MB download checked against Arm's SHA-256 and
kept in the Actions cache like Renode, so a run only downloads it when the cache is
empty. cmake and ninja come with the runner image. The unit job's small no-recommends
install is left as it is.
