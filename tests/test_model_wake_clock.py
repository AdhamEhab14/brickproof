"""Every flash model must wake Renode's clock where it makes the CPU stop early.

At the start of a RunFor, Renode's clock can miss the CPU thread starting and then wait
out a 10 ms timeout each time the CPU stops before the end of its quantum. Flash models
make it stop over and over (a translation block restart when programming is switched
on, time skipped for every operation), so a one-second slice of an update could take
450 s and be called locked up. wake_clock() ends that wait. The models run inside
Renode, so this checks their source: a new model, or a new place that stops the CPU,
must not leave it out.
"""
import ast
import os

import pytest

MODELS = os.path.join(os.path.dirname(__file__), "..", "src", "brickproof", "models")
FLASH_MODELS = sorted(f for f in os.listdir(MODELS) if f.endswith("_flash.py"))


def functions(name):
    with open(os.path.join(MODELS, name), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def calls(fn, name):
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == name
               for n in ast.walk(fn))


def test_the_flash_models_are_all_found():
    assert {"stm32f1_flash.py", "stm32f4_flash.py", "stm32l4_flash.py",
            "nrf52_flash.py"} <= set(FLASH_MODELS)


@pytest.mark.parametrize("model", FLASH_MODELS)
def test_spending_flash_time_wakes_the_clock(model):
    fns = functions(model)
    assert "wake_clock" in fns
    for name, fn in fns.items():
        if calls(fn, "SkipTime"):
            assert calls(fn, "wake_clock"), "%s: %s skips time without wake_clock()" % (model, name)


@pytest.mark.parametrize("model", FLASH_MODELS)
def test_switching_the_store_hook_on_wakes_the_clock(model):
    fns = functions(model)
    for name, fn in fns.items():
        if calls(fn, "SetHookAtMemoryAccess") and calls(fn, "RequestTranslationBlockRestart"):
            assert calls(fn, "wake_clock"), "%s: %s restarts the block without wake_clock()" % (model, name)
