"""Every relative link in the documentation leads to a file or folder that exists.

The docs moved about in the restructuring (docs/guide, docs/reference, docs/decisions), and
a link that points where a file used to be fails here instead of in a reader's browser.
"""
import glob
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = (".git", ".venv", "build", "dist", "node_modules", ".pytest_cache", ".ruff_cache")
FILES = sorted(p for p in glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True)
               if not set(os.path.relpath(p, ROOT).split(os.sep)) & set(SKIP))
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^```.*?^```", re.M | re.S)


def links(path):
    with open(path, encoding="utf-8") as f:
        text = FENCE.sub("", f.read())          # code blocks hold commands, not links
    for target in LINK.findall(text):
        if re.match(r"(https?:|mailto:|#)", target):
            continue
        yield target.split("#")[0]


def test_the_docs_are_found():
    names = {os.path.relpath(p, ROOT).replace(os.sep, "/") for p in FILES}
    assert {"README.md", "docs/README.md", "docs/reference/adapter.md", "adapters/README.md"} <= names


@pytest.mark.parametrize("path", FILES, ids=lambda p: os.path.relpath(p, ROOT).replace(os.sep, "/"))
def test_every_relative_link_resolves(path):
    broken = [t for t in links(path) if t and not os.path.exists(os.path.join(os.path.dirname(path), t))]
    assert broken == []
