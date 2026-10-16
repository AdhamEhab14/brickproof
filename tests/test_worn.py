"""Worn flash pages: flash.worn reaches the flash models."""
import re

import pytest
import yaml

from brickproof import adapter as adapters
from brickproof.engine import workdir

BASE = {"name": "x", "platform": {"base": "stm32f103"},
        "flash": {"base": 0x08000000, "size": 0x20000, "page": 0x400},
        "ram": {"size": 0x5000}, "firmware": [{"file": "a.elf"}],
        "driver": {"builtin": "staged_slot"}}


def load(tmp_path, **flash):
    d = dict(BASE, flash=dict(BASE["flash"], **flash))
    p = tmp_path / "a.yaml"
    p.write_text(yaml.safe_dump(d))
    (tmp_path / "a.elf").write_bytes(b"")          # only copied, never read here
    return adapters.load(str(p), target=str(tmp_path))


def test_a_worn_range_is_written_into_the_model(tmp_path):
    ad = load(tmp_path, worn={"from": 0x08002000, "size": 0x400})
    assert ad.flash.worn == (0x08002000, 0x08002400)
    workdir.prepare(str(tmp_path / "w"), ad)
    model = (tmp_path / "w" / "models" / "stm32f1_flash.py").read_text()
    assert "WORN_FROM = 0x8002000" in model and "WORN_TO = 0x8002400" in model


def test_no_worn_pages_by_default(tmp_path):
    ad = load(tmp_path)
    assert ad.flash.worn is None
    workdir.prepare(str(tmp_path / "w"), ad)
    model = (tmp_path / "w" / "models" / "stm32f1_flash.py").read_text()
    assert re.search(r"^WORN_FROM = 0x0\b", model, re.M)
    assert re.search(r"^WORN_TO = 0x0\b", model, re.M)


def test_a_worn_range_outside_the_flash_is_refused(tmp_path):
    with pytest.raises(adapters.AdapterError, match="flash.worn"):
        load(tmp_path, worn={"from": 0x0801FC00, "size": 0x800})
