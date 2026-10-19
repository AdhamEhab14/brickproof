"""brickproof setup: the download is checked against a pinned SHA-256 and unpacked only
inside BrickProof's folder. No network here: the fetch is replaced."""
import hashlib
import io
import os
import zipfile

import pytest

from brickproof import setup


def fake_zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "home", lambda: str(tmp_path / ".brickproof"))
    monkeypatch.setattr(setup, "this_system", lambda: ("win32", "x86_64"))
    return tmp_path


def use_archive(monkeypatch, data, digest=None):
    name = "renode-test.zip"
    monkeypatch.setattr(setup, "BUILDS", {("win32", "x86_64"): (
        name, digest or hashlib.sha256(data).hexdigest(), "renode.exe")})

    def fetch(_url, path, _say):
        with open(path, "wb") as f:
            f.write(data)
    return fetch


def test_downloads_checks_and_unpacks(sandbox, monkeypatch):
    fetch = use_archive(monkeypatch, fake_zip({"renode_1.17/renode.exe": b"MZ"}))
    said = []
    path = setup.setup(say=said.append, fetch=fetch)
    assert os.path.basename(path) == "renode.exe" and os.path.isfile(path)
    assert setup.installed() == path
    assert any("SHA-256" in s for s in said)
    # a second time it is already there: no download
    assert setup.setup(say=said.append, fetch=None) == path


def test_a_download_that_does_not_match_is_not_installed(sandbox, monkeypatch):
    fetch = use_archive(monkeypatch, fake_zip({"renode.exe": b"MZ"}), digest="0" * 64)
    with pytest.raises(RuntimeError, match="SHA-256"):
        setup.setup(say=lambda _s: None, fetch=fetch)
    assert setup.installed() is None


def test_an_archive_cannot_write_outside_its_folder(sandbox, monkeypatch):
    fetch = use_archive(monkeypatch, fake_zip({"../../evil.exe": b"x", "renode.exe": b"MZ"}))
    with pytest.raises(ValueError, match="outside"):
        setup.setup(say=lambda _s: None, fetch=fetch)
    assert not (sandbox / "evil.exe").exists()


def test_a_system_without_a_portable_build_says_what_to_do(sandbox, monkeypatch):
    monkeypatch.setattr(setup, "this_system", lambda: ("darwin", "arm64"))
    with pytest.raises(RuntimeError, match="RENODE_PATH"):
        setup.setup(say=lambda _s: None, fetch=None)
