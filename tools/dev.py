"""The commands for working on BrickProof, in one place. Run from anywhere in the repository:

    python tools/dev.py check            lint and the unit tests: what every pull request runs first
    python tools/dev.py lint             ruff
    python tools/dev.py test [ARGS]      the unit tests (no emulator); ARGS go to pytest
    python tools/dev.py renode           the flash models' chip rules, in Renode (RENODE_PATH)
    python tools/dev.py scenario ID...   campaigns from tests/scenarios.yaml, e.g. demo-f411
    python tools/dev.py parity FOLDER    compare a folder of JSON reports with the parity baseline
    python tools/dev.py docs             the documentation's links

It uses this checkout's source (src/), so nothing needs installing first but the
dependencies: pip install -e ".[dev]".
"""
import os
import shlex
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def run(*args):
    path = os.path.join(ROOT, "src") + os.pathsep + os.environ.get("PYTHONPATH", "")
    env = dict(os.environ, PYTHONPATH=path)
    print("$ " + " ".join(args), flush=True)
    return subprocess.call(list(args), cwd=ROOT, env=env)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    py = sys.executable
    if cmd == "lint":
        return run(py, "-m", "ruff", "check", ".")
    if cmd == "test":
        return run(py, "-m", "pytest", "-q", "tests", "--ignore=tests/renode", *rest)
    if cmd == "check":
        return (run(py, "-m", "ruff", "check", ".")
                or run(py, "-m", "pytest", "-q", "tests", "--ignore=tests/renode"))
    if cmd == "renode":
        return run(py, "-m", "pytest", "-q", "tests/renode", *rest)
    if cmd == "docs":
        return run(py, "-m", "pytest", "-q", "tests/test_docs_links.py")
    if cmd == "scenario":
        if not rest:
            print("which? e.g.: python tools/dev.py scenario demo-f411 (the ids are in tests/scenarios.yaml)")
            return 2
        ids = [a for i in rest for a in ("--id", i)]
        # scenarios.py splits --command like a shell would: the interpreter's path is quoted,
        # so one with spaces (D:\Embedded projects\...) stays one argument
        command = "%s -m brickproof.cli" % shlex.quote(py.replace("\\", "/"))
        return run(py, os.path.join("tools", "scenarios.py"), "run", *ids, "--command", command)
    if cmd == "parity":
        if len(rest) != 1:
            print("usage: python tools/dev.py parity <folder of reports>")
            return 2
        return run(py, os.path.join("tools", "parity.py"), "compare",
                   os.path.join("tests", "parity", "baseline.json"), rest[0])
    print("no command %r (python tools/dev.py help)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
