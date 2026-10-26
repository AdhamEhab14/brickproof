"""Every key an adapter may have, in one place.

The parser (adapter.py) reads what it needs and used to pass over anything else in
silence, so `boot_setle: 3` or `flash: {write_units: 4}` ran with the default and no word
said. `unknown(data)` names every key that is not here, with the nearest one that is;
`brickproof check` fails on them, and so does `brickproof run`, which makes the same checks
before it starts an emulator. The adapter reference
(docs/reference/adapter.md) is checked against this list by a test, so the two cannot
drift apart.

A value is None for a key that takes a value (a number, a string, a list of them), a
dict for a mapping with known keys, [dict] for a list of such mappings, and USER for a
mapping whose keys are the user's own (pin names, image names, driver options).
"""
import difflib

USER = "user's own keys"

RANGE = {"from": None, "size": None}

SCHEMA = {
    "name": None,
    "target": None,
    "extends": None,
    "platform": {"base": None, "extra": None},
    "flash": {
        "base": None, "size": None, "page": None, "sectors": None, "write_unit": None,
        "write_protected": [RANGE], "read_protected": None, "pcrop": [RANGE], "uicr": USER,
        "reset_on": None, "hardware_watchdog": None, "timing": None, "worn": RANGE,
    },
    "external_flash": {"bus": None, "cs": None, "size": None, "address": None, "status": None,
                       "wp": None, "endurance": None},
    "external_eeprom": {"bus": None, "size": None, "page": None, "i2c_address": None,
                        "address_bytes": None, "address": None, "endurance": None},
    "ram": {"size": None, "base": None},
    "firmware": [{"file": None, "addr": None}],
    "clock": {"hse": None},
    "pins": USER,
    "uart": None,
    "boot_settle": None,
    "reset": None,
    "cpu": {"vector_table": None, "mips": None},
    "low_power": {"wake_after": None},
    "option_bytes": USER,                       # m33mu chips: option bytes by name
    "driver": {"builtin": None, "file": None, "options": USER},
    "oracle": {
        "images": USER, "accept": None, "stable_for": None,
        "run_in": {"start": None, "end": None}, "samples": None, "interval": None,
    },
    "scenario": {
        "name": None, "update_time": None, "cut_limit": None, "check_states": None,
        "plan": {"mode": None, "per_phase": None, "small": None, "real_every": None},
        "torn": None, "torn_seed": None,
        "depth": {"levels": None, "mode": None, "per_phase": None, "small": None,
                  "max_states": None, "torn": None},
        "cuts": [{"name": None, "at_op": None, "on_erase": None,
                  "at_ops": {"from": None, "to": None, "step": None},
                  "expect": {"kind": None, "addr": None}}],
        "content_faults": {"keep": None, "image_size": None, "mutations": None,
                           "regions": USER, "images": USER},
        "bit_errors": {"flips": None, "runs": None, "seed": None, "regions": USER},
        "link_cuts": {"points": None, "wait": None},
    },
}


def unknown(data, schema=SCHEMA, where=""):
    """[(path, key, suggestion or None)] for every key of `data` the schema does not have.
    A key whose value is not a mapping where one is allowed (`plan: phases`, `torn: true`,
    `link_cuts: true`) is fine: the parser decides what such values mean."""
    out = []
    if not isinstance(data, dict) or not isinstance(schema, dict):
        return out
    for key, value in data.items():
        path = "%s.%s" % (where, key) if where else str(key)
        if key not in schema:
            near = difflib.get_close_matches(str(key), [str(k) for k in schema], n=1, cutoff=0.7)
            out.append((path, key, near[0] if near else None))
            continue
        sub = schema[key]
        if sub is None or sub == USER:
            continue
        if isinstance(sub, list):
            if isinstance(value, list):
                for i, item in enumerate(value):
                    out += unknown(item, sub[0], "%s[%d]" % (path, i))
        else:
            out += unknown(value, sub, path)
    return out


def paths(schema=SCHEMA, where=""):
    """Every key of the schema, as a dotted path (lists as [])."""
    for key, sub in schema.items():
        path = "%s.%s" % (where, key) if where else key
        yield path
        if isinstance(sub, dict):
            yield from paths(sub, path)
        elif isinstance(sub, list):
            yield from paths(sub[0], path + "[]")
