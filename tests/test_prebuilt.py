"""Committed firmware is exactly what its SHA256SUMS says.

The demo and the targets CI runs from prebuilt files keep a SHA256SUMS next to them. A
binary that changes without its checksum changing (a rebuild committed by accident, a line
ending conversion) fails here, before it can quietly change what the campaigns test. A
deliberate rebuild updates SHA256SUMS in the same commit:
`sha256sum $(ls | grep -v SHA256SUMS) > SHA256SUMS` in that folder.
"""
import glob
import hashlib
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# where committed firmware lives (not build/ or a virtualenv)
PREBUILT = [p for top in ("examples", "adapters")
            for p in glob.glob(os.path.join(ROOT, top, "**", "prebuilt", "**", "*"), recursive=True)]
SUMS = sorted(p for p in PREBUILT if os.path.basename(p) == "SHA256SUMS")


def listed(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            digest, name = line.rstrip("\n").split("  ", 1)
            out[name] = digest
    return out


def test_every_prebuilt_folder_has_checksums():
    folders = {os.path.dirname(p) for p in PREBUILT
               if os.path.isfile(p) and not p.endswith(("SHA256SUMS", "README.md"))}
    assert folders and folders == {os.path.dirname(s) for s in SUMS}


@pytest.mark.parametrize("sums", SUMS, ids=lambda p: os.path.relpath(os.path.dirname(p), ROOT))
def test_the_files_are_the_ones_listed(sums):
    folder = os.path.dirname(sums)
    want = listed(sums)
    have = sorted(f for f in os.listdir(folder) if f not in ("SHA256SUMS", "README.md")
                  and os.path.isfile(os.path.join(folder, f)))
    assert have == sorted(want), "a file was added or removed without updating SHA256SUMS"
    for name, digest in want.items():
        with open(os.path.join(folder, name), "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == digest, "%s changed" % name
