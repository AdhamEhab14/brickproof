"""The version is in one place, and everything that names it agrees.

src/brickproof/__init__.py holds it; the package reads it from there (pyproject.toml), and
so does the release workflow when it checks the tag. The GitHub Action examples a user
copies name the latest release, which is that version, and the changelog has its section
(or, between releases, an Unreleased section on top). A release once failed because the
version was bumped in one place and not another.
"""
import os
import re

import brickproof

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = brickproof.__version__


def text(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


def test_the_package_takes_its_version_from_the_module():
    pyproject = text("pyproject.toml")
    table = re.search(r"^\[project\]\n(.*?)^\[", pyproject, re.M | re.S).group(1)
    assert not re.search(r"^version\s*=", table, re.M), "no second copy in [project]"
    assert 'dynamic = ["version"]' in table
    assert 'version = {attr = "brickproof.__version__"}' in pyproject


def test_the_action_examples_name_this_version():
    for path in (("README.md",), ("docs", "guide", "results-and-ci.md")):
        tags = re.findall(r"AdhamEhab14/brickproof@v([0-9.]+)", text(*path))
        assert tags and set(tags) == {VERSION}, path


def test_the_changelog_has_this_version_or_an_unreleased_section_on_top():
    heads = re.findall(r"^## (.+)$", text("CHANGELOG.md"), re.M)
    assert heads[0] == "Unreleased" or heads[0].split()[0] in (VERSION, "v" + VERSION)
    assert any(h.split()[0] in (VERSION, "v" + VERSION) for h in heads), "the released version has a section"
