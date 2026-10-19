"""brickproof setup: get the emulator, so nobody has to install Renode and set RENODE_PATH.

Downloads Renode's portable build for this system from Renode's GitHub releases into
BrickProof's own folder (~/.brickproof), checks it against the SHA-256 Renode publishes, and
unpacks it. find_renode() looks there, so nothing needs setting afterwards. The version and
checksums are pinned: BrickProof is tested on this Renode.
"""
import hashlib
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

VERSION = "1.17.0"
RELEASE = "https://github.com/renode/renode/releases/download/v%s/" % VERSION
# (file, its SHA-256 as Renode's release lists it, the executable inside)
BUILDS = {
    ("win32", "x86_64"): ("renode-%s.windows-portable.zip" % VERSION,
                          "18bcf145422039e8702c3e5f9864c7787561bfd5deb7a3ee6e168ecf19e2b9db",
                          "renode.exe"),
    ("linux", "x86_64"): ("renode-%s.linux-portable.tar.gz" % VERSION,
                          "4ba7c68b59e2447f188ef4b4b112fcccd2802582c460beedceb63b84e5605a5f",
                          "renode"),
    ("linux", "arm64"): ("renode-%s.linux-arm64-portable.tar.gz" % VERSION,
                         "e9051578411441bfb47b77de0381cfba3badce03663367fab561472fd7807f1f",
                         "renode"),
}


def home():
    """Where BrickProof keeps what it downloads."""
    return os.path.join(os.path.expanduser("~"), ".brickproof")


def install_dir():
    return os.path.join(home(), "renode-%s" % VERSION)


def this_system():
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)
    return ("win32" if sys.platform == "win32" else sys.platform), arch


def installed():
    """The Renode executable setup installed, or None."""
    found = BUILDS.get(this_system())
    if not found:
        return None
    for folder, _dirs, files in os.walk(install_dir()):
        if found[2] in files:
            path = os.path.join(folder, found[2])
            if os.access(path, os.X_OK) or sys.platform == "win32":
                return path
    return None


def _safe_members(names, dest):
    """Every archive member must land inside `dest`: a hostile archive cannot write
    elsewhere ('../', absolute paths, drive letters)."""
    root = os.path.realpath(dest)
    for name in names:
        target = os.path.realpath(os.path.join(dest, name))
        if os.path.commonpath([root, target]) != root:
            raise ValueError("refusing to unpack %r: it would land outside %s" % (name, dest))


def unpack(archive, dest):
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            _safe_members(z.namelist(), dest)
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            members = [m for m in t.getmembers() if not (m.issym() or m.islnk()) or
                       os.path.commonpath([os.path.realpath(dest), os.path.realpath(
                           os.path.join(dest, os.path.dirname(m.name), m.linkname))])
                       == os.path.realpath(dest)]
            _safe_members([m.name for m in members], dest)
            t.extractall(dest, members=members)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, path, say=print):
    """Fetch `url` to `path`, printing progress every 10%."""
    with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got, shown = 0, 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total and got * 10 // total > shown:
                shown = got * 10 // total
                say("  %d%% of %d MB" % (shown * 10, total >> 20))


def setup(say=print, fetch=download):
    """Install Renode for this system unless it is already there. Returns its path."""
    have = installed()
    if have:
        say("Renode %s is already set up: %s" % (VERSION, have))
        return have
    system = this_system()
    build = BUILDS.get(system)
    if not build:
        raise RuntimeError(
            "no portable Renode %s for %s/%s here. Install it from "
            "https://github.com/renode/renode/releases (on a Mac, the .dmg), then set RENODE_PATH "
            "to the renode program" % (VERSION, system[0], system[1]))
    name, digest, exe = build
    os.makedirs(home(), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="renode-", dir=home())
    try:
        archive = os.path.join(tmp, name)
        say("Downloading Renode %s (%s) from GitHub..." % (VERSION, name))
        fetch(RELEASE + name, archive, say)
        if sha256(archive) != digest:
            raise RuntimeError("the download does not match Renode's published SHA-256; nothing "
                               "was installed. Try again later.")
        say("Checked against Renode's SHA-256. Unpacking...")
        dest = install_dir()
        shutil.rmtree(dest, ignore_errors=True)
        unpack(archive, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    path = installed()
    if not path:
        raise RuntimeError("Renode was unpacked into %s but %s is not in it" % (install_dir(), exe))
    if sys.platform != "win32":
        os.chmod(path, os.stat(path).st_mode | 0o111)
    say("Renode is set up: %s. BrickProof finds it there; nothing else to set." % path)
    return path
