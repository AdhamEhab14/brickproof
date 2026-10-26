"""Deciding one result: what the firmware did wrong, a program cut that landed, the
oracle's and the driver's verdict, and a hang checked twice before it is believed."""
import functools

from brickproof import trace as traces


def _fault_message(session):
    """Something the firmware did that the emulator lets pass and the chip does not."""
    v = session.violations()
    if v["fault"]:
        return ("bus fault: the firmware touched 0x%08X (PC 0x%08X), which does not exist on "
                "the chip" % v["fault"])
    if v["refused"]:
        return ("flash rule broken: the chip refused %d program(s), first at 0x%08X, and kept "
                "the old value. On an STM32F1 that is a cell that was not erased (PGERR), on an "
                "STM32F4 a store that is not as wide as PSIZE says (PGPERR) or does not fit in one "
                "16-byte flash row (PGAERR), on an STM32L4 a double word that is not erased "
                "(PROGERR), not two whole words in order (SIZERR, PGAERR) or programmed while an "
                "earlier error was still flagged (PGSERR), on an STM32H5 a 128-bit word that was "
                "already programmed (PGSERR), on an nRF52 a store that is not a whole aligned word "
                "or a third write to a word without an erase (nWRITE)" % v["refused"])
    if v.get("pcrop"):
        if session.flash.model == "nrf52_flash.py":
            return ("protected read: %d read(s) in an ACL region with READ disabled, first at "
                    "0x%08X. The chip blocks them with a bus fault" % v["pcrop"])
        return ("proprietary code read as data: %d read(s) of a PCROP sector, first at 0x%08X. "
                "The chip only lets that code run; a data read gets RDERR, not the code"
                % v["pcrop"])
    if v.get("protected"):
        n, at = v["protected"]
        if session.flash.external(at):
            return ("write protection: %d erase or program operation(s) in the external flash chip "
                    "were refused, first at 0x%08X. Its status register (BP, TB, SEC, CMP) protects "
                    "that part, so the chip ignores the command" % (n, at))
        if session.flash.model == "nrf52_flash.py":
            return ("write protection: %d erase or program operation(s) in an ACL region with WRITE "
                    "disabled were refused, first at 0x%08X. The chip blocks them with a bus fault"
                    % (n, at))
        return ("write protection: %d erase or program operation(s) in write-protected flash "
                "were refused, first at 0x%08X. The option bytes protect that part of flash, so the "
                "chip changes nothing there" % (n, at))
    if v["stray"]:
        return ("flash changed at 0x%08X with no flash operation behind it (a store with PG "
                "clear or the controller locked). The chip ignores such a write" % v["stray"])
    return None


def _rewind_program(session, golden, res):
    """Make a program cut land exactly before its halfword.

    The model stops the CPU when PG is set, but Renode finishes the instruction block
    it is in, and that block usually holds the store too. Left alone, "cut at op N"
    would mean "after op N", and the state right after an erase, with nothing
    programmed yet, would never be tested. If the halfword did land, put back what
    was there before it."""
    op = golden.ops[res.op_index]
    if "value" not in op:
        return                                             # it wrote what was already there
    before = traces.value_before(golden.ops, res.op_index, golden.pre, golden.flash)
    # Compared with what was there before, not with the traced value: the two can differ
    # at this instant. An option byte is traced as the chip stores it (the byte and its
    # complement), but until the program is settled the cell holds what was written.
    size = traces.size_of(op, golden.flash)
    if session.read_unit(res.addr, size) != before:
        session.write_unit(res.addr, before, size)
        res.rewound = True


def _verdict(session, driver, adapter, res, oracle, update_op=None):
    """Power up and judge. Three voices, and any one of them can fail the run: what
    the chip would not have allowed, the oracle (from outside the firmware), and the
    driver (the firmware's own signs of life). A power cycle clears the fault latch,
    so it is read before each one.

    `update_op` is the operation of the update the (first) cut fell before, None for
    the update left to finish. A driver that judges by it has a judging() method."""
    if hasattr(driver, "judging"):
        driver.judging(update_op)
    session.power_cycle(settle=adapter.boot_settle)     # RAM gone, flash as it was left
    res.alive = bool(driver.alive())
    fault = _fault_message(session)
    if fault:
        res.alive = False
        res.message = fault
        return
    if not res.alive:
        res.message = "the device did not come back"
        return
    if oracle:
        v = oracle.judge(session)
        res.image = v.image
        if not v.ok:
            res.message = v.message
            return
    res.recovered, msg = driver.check_recovered()
    fault = _fault_message(session)
    if fault:
        res.recovered = False
        msg = fault
    elif res.recovered and oracle:
        # the driver's checks may have poked the device (a rollback probe stages an
        # older image and reboots), so look once more at what it ended up as. That it
        # keeps running was seen the first time.
        v = oracle.judge(session, stable=False)
        res.image = v.image
        if not v.ok:
            res.recovered = False
            msg = "after the driver's checks: " + v.message
    res.message = msg or ""
    res.passed = res.recovered


def _hang_confirmed(run):
    """Repeat a run that hung, on the fresh emulator the hang left, before it is
    reported. Renode replays a run exactly, so firmware that locks up does it again;
    an emulator that stalled by itself does not, and the second run is the result. The
    stall seen on CI (Renode's clock missing a wake-up) is now prevented in the flash
    models; this stays for any other emulator trouble, which must not pass as a lock-up."""
    @functools.wraps(run)
    def once_more(*args, **kw):
        first = run(*args, **kw)
        if not first.hung:
            return first
        res = run(*args, **kw)
        res.seconds = round(res.seconds + first.seconds, 1)
        return res
    return once_more


def _failed(r):
    return not (r.passed or r.skipped)
