"""A failing state, as files to put on a real board.

`brickproof export` runs the update once, uninterrupted, then replays it to just before
the operation a cut was made at: the same bytes a cut there leaves, and the same bytes
the campaign powers the emulator up from (`--torn KIND` leaves that operation half
done, with the same seed the campaign uses). The flash image is split into what a
programmer writes separately: the chip's flash, its option bytes, and an external
flash chip with its status registers.
"""
import os

from brickproof import torn as torns
from brickproof import trace as traces


def state_image(pre, ops, flash, cut, torn=None, seed=0):
    """The whole flash image just before operation `cut`, or with it torn."""
    if not 0 <= cut <= len(ops):
        raise ValueError("the update has %d operations: --cut takes 0 to %d" % (len(ops), len(ops)))
    before = bytes(traces.Replay(pre, ops, flash).at(cut))
    if torn is None:
        return before
    if cut == len(ops):
        raise ValueError("there is no operation %d to tear: the update ends before it" % cut)
    for state in torns.states(ops[cut], before, flash, (torn,), seed):
        return state.image
    raise ValueError("operation %d (%s at 0x%08X) has no %s state: that shape does not apply "
                     "to it, or leaves the same flash as a clean cut" % (
                         cut, ops[cut]["kind"], ops[cut]["addr"], torn))


def parts(image, flash):
    """[(name, address, bytes)]: the flash, then the option bytes and the external chip
    where the board has them."""
    out = [("flash", flash.base, image[:flash.size])]
    at = flash.size
    if flash.ob_size:
        out.append(("option bytes", flash.ob_base, image[at:at + flash.ob_size]))
        at += flash.ob_size
    if flash.ext_size:
        out.append(("external flash", 0, image[at:at + flash.ext_size]))
        at += flash.ext_size
        out.append(("external status registers", None, image[at:]))
    return out


def file_names(out):
    """Where each part goes, next to `out` (the flash image itself)."""
    stem = os.path.splitext(out)[0]
    return {"flash": out, "option bytes": stem + ".ob.bin",
            "external flash": stem + ".ext.bin",
            "external status registers": stem + ".ext-status.bin",
            "readme": stem + ".txt"}


def readme(adapter, cut, torn, written):
    """How to put `written` ({part name: (path, address, bytes)}) on a board."""
    name = os.path.basename(written["flash"][0])
    what = "torn %s at operation %d" % (torn, cut) if torn else "a power cut just before operation %d" % cut
    lines = ["The flash of %s after %s." % (adapter.name, what), "",
             "Made by: brickproof export %s --cut %d%s" % (
                 getattr(adapter, "path", "") or "adapter.yaml", cut, " --torn " + torn if torn else ""),
             "", "Files:"]
    for part, (path, addr, data) in written.items():
        at = "" if addr is None else " at 0x%08X" % addr
        lines.append("  %-26s %s, %d bytes%s" % (part, os.path.basename(path), len(data), at))
    lines += ["", "Write the whole flash (erase everything first, so nothing of what was there "
              "before is left), then reset the board:", ""]
    base = written["flash"][1]
    if adapter.platform.startswith("stm32"):
        lines += ["  STM32CubeProgrammer:  STM32_Programmer_CLI -c port=SWD -e all -w %s 0x%08X -v -rst"
                  % (name, base),
                  "  ST-LINK utility:      ST-LINK_CLI -c SWD -ME -P %s 0x%08X -V -Rst" % (name, base)]
    elif adapter.platform.startswith("nrf52"):
        hexname = os.path.splitext(name)[0] + ".hex"
        lines += ["  nrfjprog takes Intel HEX:",
                  "  arm-none-eabi-objcopy -I binary -O ihex --change-addresses 0x%X %s %s"
                  % (base, name, hexname),
                  "  nrfjprog --program %s --chiperase --verify --reset" % hexname]
    if "option bytes" in written:
        lines += ["", "The option bytes are in their own file. Compare them with what the board "
                  "holds before writing them: a wrong value can lock the chip (read protection) "
                  "or make it erase itself."]
    if "external flash" in written:
        lines += ["", "The external flash chip's contents and status registers are in their own "
                  "files. Write them with whatever programs that chip on the board (a clip-on "
                  "programmer, or a small loader on the microcontroller)."]
    return "\n".join(lines) + "\n"


def write(adapter, pre, ops, out, cut, torn=None):
    """Write the state's files. Returns {part name: path}, the readme included."""
    image = state_image(pre, ops, adapter.flash, cut, torn, adapter.torn_seed)
    names = file_names(out)
    written = {}
    for part, addr, data in parts(image, adapter.flash):
        with open(names[part], "wb") as f:
            f.write(data)
        written[part] = (names[part], addr, data)
    with open(names["readme"], "w", encoding="utf-8") as f:
        f.write(readme(adapter, cut, torn, written))
    paths = {part: path for part, (path, _a, _d) in written.items()}
    paths["readme"] = names["readme"]
    return paths
