"""An MCUboot adapter written from a Zephyr build.

    brickproof adapter-from-zephyr <MCUboot build folder> --images <folder> -o adapter.yaml

The MCUboot build folder is the one `west build` made for MCUboot (it holds
zephyr/zephyr.dts and zephyr/.config). The images folder holds mcuboot.elf and the signed
app images, as adapters/mcuboot/build.py leaves them: app_v1.img (installed in slot 0),
app_v2_staged.img (padded, with the trailer that asks for the upgrade, staged in slot 1)
and app_v2.img (what slot 0 must hold afterwards).

From the build it takes: the chip (CONFIG_SOC), MCUboot's upgrade mode, the flash (its base,
size and write and erase sizes), the RAM, the slots, the console UART and an STM32 board's
crystal. It knows the sector layout of the STM32F4 parts BrickProof models, which the
devicetree does not give.
"""
import os
import re

# CONFIG_SOC prefix -> (BrickProof platform, flash layout: page size or sector list)
CHIPS = [
    ("stm32f411", "stm32f411", {"sectors": [0x4000] * 4 + [0x10000] + [0x20000] * 3}),
    ("stm32f103", "stm32f103", {"page": 0x400}),
    ("nrf52840", "nrf52840", {"page": None}),       # the erase-block-size from the devicetree
]
MODES = {
    "BOOT_SWAP_USING_SCRATCH": "swap-scratch",
    "BOOT_SWAP_USING_MOVE": "swap-move",
    "BOOT_SWAP_USING_OFFSET": "swap-offset",
    "BOOT_UPGRADE_ONLY": "overwrite",
}


class DtsNode:
    def __init__(self, name, labels):
        self.name, self.labels = name, labels
        self.props = {}
        self.children = []

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def parse_dts(text):
    """The root node of a flattened devicetree source (zephyr.dts)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    root = DtsNode("/", [])
    stack = [root]
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("/dts-v1/"):
            continue
        m = re.match(r"^((?:[\w-]+:\s*)*)([\w,@.+/-]+)\s*\{$", line)
        if m:
            node = DtsNode(m.group(2), re.findall(r"([\w-]+):", m.group(1)))
            stack[-1].children.append(node)
            stack.append(node)
        elif line.startswith("};"):
            stack.pop()
        else:
            m = re.match(r"^([\w,#.+-]+)\s*(?:=\s*(.*?))?;$", line)
            if m:
                stack[-1].props[m.group(1)] = (m.group(2) or "").strip()
    return root


def cells(value):
    """The numbers in a `< ... >` property."""
    return [int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+|\d+", value.split("<", 1)[-1])]


def by_label(root, label):
    for node in root.walk():
        if label in node.labels:
            return node
    return None


def parse_kconfig(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"^CONFIG_(\w+)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip('"')
    return out


def describe(build):
    """What an adapter needs, from an MCUboot build folder, as a dict."""
    with open(os.path.join(build, "zephyr", "zephyr.dts"), encoding="utf-8") as f:
        dts = parse_dts(f.read())
    with open(os.path.join(build, "zephyr", ".config"), encoding="utf-8") as f:
        kconfig = parse_kconfig(f.read())

    soc = kconfig.get("SOC", "")
    chip = next((c for c in CHIPS if soc.startswith(c[0])), None)
    if chip is None:
        raise ValueError("CONFIG_SOC=%s: BrickProof models %s" % (soc, ", ".join(c[0] for c in CHIPS)))
    chosen = next((n for n in dts.walk() if n.name == "chosen"), None)
    if chosen is None:
        raise ValueError("the devicetree has no /chosen node")

    def chosen_node(prop):
        ref = chosen.props.get(prop, "").lstrip("&")
        node = by_label(dts, ref)
        if node is None:
            raise ValueError("chosen %s (%s) is not in the devicetree" % (prop, ref or "unset"))
        return node, ref

    flash, _ = chosen_node("zephyr,flash")
    sram, _ = chosen_node("zephyr,sram")
    _, console = chosen_node("zephyr,console")
    base, size = cells(flash.props["reg"])[:2]
    layout = dict(chip[2])
    if "page" in layout and layout["page"] is None:
        layout["page"] = cells(flash.props["erase-block-size"])[0]
    if "sectors" in layout and sum(layout["sectors"]) != size:
        raise ValueError("%s: flash is 0x%X here, the sector table is for 0x%X"
                         % (soc, size, sum(layout["sectors"])))
    slots = {}
    for part in by_label(dts, "boot_partition"), by_label(dts, "slot0_partition"), \
            by_label(dts, "slot1_partition"):
        if part is None:
            raise ValueError("the devicetree needs boot_partition, slot0_partition and slot1_partition")
        off, length = cells(part.props["reg"])[:2]
        slots[part.labels[0]] = (base + off, length)
    mode = next((MODES[k] for k in MODES if kconfig.get(k) == "y"), "swap")
    hse = by_label(dts, "clk_hse")
    return {
        "soc": soc, "board": kconfig.get("BOARD_TARGET", kconfig.get("BOARD", "")),
        "platform": chip[1], "flash_base": base, "flash_size": size, "layout": layout,
        "write_unit": cells(flash.props.get("write-block-size", "<1>"))[0],
        "ram_size": cells(sram.props["reg"])[1], "uart": console,
        "slot0": slots["slot0_partition"], "slot1": slots["slot1_partition"],
        "boot": slots["boot_partition"], "mode": mode,
        "hse": cells(hse.props["clock-frequency"])[0]
        if hse is not None and "clock-frequency" in hse.props and chip[1].startswith("stm32") else None,
    }


def adapter_yaml(d, images, alive="APP v[0-9]", expect="APP v2"):
    """The adapter text for a description from describe()."""
    if "sectors" in d["layout"]:
        layout = "  sectors: [%s]" % ", ".join("0x%X" % s for s in d["layout"]["sectors"])
    else:
        layout = "  page: 0x%X" % d["layout"]["page"]
    clock = "\nclock:\n  hse: %d\n" % d["hse"] if d["hse"] else ""
    return """# MCUboot on %(board)s (%(soc)s), %(mode)s, written by `brickproof adapter-from-zephyr`
# from the MCUboot build. Slot 0 at 0x%(s0)X and slot 1 at 0x%(s1)X, 0x%(slen)X bytes each.

name: mcuboot_%(name)s
target: %(images)s

platform:
  base: %(platform)s

flash:
  base: 0x%(fbase)X
  size: 0x%(fsize)X
%(layout)s
  write_unit: %(wu)d

ram:
  size: 0x%(ram)X

firmware:
  - file: mcuboot.elf
  - file: app_v1.img
    addr: 0x%(s0)X
%(clock)s
uart: %(uart)s
boot_settle: 0.5

driver:
  builtin: staged_slot
  options:
    slot: 0x%(s1)X
    image: app_v2_staged.img
    alive: "%(alive)s"
    expect: "%(expect)s"
    boot_timeout: 30

oracle:
  images:
    v1: {file: app_v1.img, at: 0x%(s0)X}
    v2: {file: app_v2.img, at: 0x%(s0)X}
  accept: [v2]

scenario:
  name: %(mode)s-v1-to-v2
  update_time: 30
  cut_limit: 40
  plan: {mode: phases, per_phase: 4}
""" % {"board": d["board"], "soc": d["soc"], "mode": d["mode"], "s0": d["slot0"][0],
       "s1": d["slot1"][0], "slen": d["slot0"][1],
       "name": re.sub(r"[^a-z0-9]+", "_", d["board"].lower()).strip("_"),
       "images": images.replace("\\", "/"), "platform": d["platform"], "fbase": d["flash_base"],
       "fsize": d["flash_size"], "layout": layout, "wu": d["write_unit"], "ram": d["ram_size"],
       "clock": clock, "uart": d["uart"], "alive": alive, "expect": expect}
