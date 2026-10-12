/* BrickProof demo bootloader: overwrite-style A/B update with a rollback floor.
 *
 * A new image is dropped into Slot B (by an OTA agent, a debugger, BrickProof).
 * On the next boot this copies it over Slot A and runs it. The order of the
 * install is what makes it survive a power cut at any flash operation:
 *
 *   1. raise the rollback floor to the new version (two-copy record, see meta_write)
 *   2. erase Slot A
 *   3. copy the app body
 *   4. copy the header last, so Slot A only looks valid once it is complete
 *   5. mark Slot B consumed
 *
 * Until step 5, Slot B is still a valid image, so a cut anywhere earlier just
 * means the next boot runs the install again.
 *
 * Build options put back known bugs. The first four are real, from another
 * bootloader (three found by BrickProof, one by a real board). The last two are
 * classic flash mistakes that an emulator's plain memory lets through and a chip
 * does not. Each one should make a run fail:
 *   BUG_CONSUME_FIRST     mark Slot B consumed before copying (cut = no image left)
 *   BUG_TRUST_HEADER      copy the header first and check only its magic, not the CRC
 *                         (cut = a half-copied image that looks valid)
 *   BUG_NAIVE_FLOOR       keep the floor in one page, erase it and rewrite it after
 *                         the install (cut = floor back to 0, old images accepted again)
 *   BUG_POP_AFTER_SWITCH  pop saved registers after switching to the app's stack
 *                         (no cut needed: it reads past the end of RAM on every boot)
 *   BUG_NO_ERASE          copy the new image over the old one without erasing first
 *                         (an F1 refuses to program a cell that is not erased; an F4
 *                         stores old AND new, which is neither image)
 *   BUG_NO_UNLOCK         never unlock the flash controller for the install
 *                         (the chip ignores every erase and program)
 *   BUG_RESUME_COPY       after an interrupted install, skip the erase and write only
 *                         the cells still missing. Survives every clean cut. A cut
 *                         inside a program leaves one cell half written, and an F1
 *                         will not program that cell again without an erase. (An F4
 *                         will, so this one is a bug on the F1 only.)
 *   BUG_RETRY_LIMIT       give up on an update after two interrupted attempts. Survives
 *                         any single power cut. Two cuts in a row, the second during
 *                         the recovery from the first, leave no image at all.
 *   BUG_SELF_LOCK         write-protect the bootloader's own flash from the bootloader,
 *                         in the field. Option bytes are erased before they are written
 *                         back. A cut in between leaves the chip read-protected, and
 *                         when the next boot writes "unprotected" again the chip
 *                         answers by mass-erasing the flash.
 *
 *   BUG_EARLY_UNPG        program one cell properly, then store the next one after PG has
 *                         been cleared again. An emulator's plain memory takes that
 *                         second store. The chip ignores it, so half the image is
 *                         never written, power cut or not.
 *   BUG_WATCHDOG          feed the watchdog between flash operations, but leave it at
 *                         its reset timeout of half a second. On a device with a
 *                         hardware watchdog, a sector erase that takes a second gets
 *                         the chip reset in the middle of it, on every attempt.
 *
 * HOLD_PG is not a bug: it is the other common way to write flash, with PG left set
 * over a whole run of cells. A power cut can fall between any two of them.
 *
 * The same source builds for an STM32F103 and, with -DSTM32F4, for an STM32F411. What
 * differs between them (the flash map, how to erase and program, the option bytes)
 * is in common/chip_*.h.
 */
#include "demo.h"

#define META_MAGIC  0x4D455441u   /* "ATEM" */

typedef struct {
    uint32_t seq;
    uint32_t floor;
    uint32_t magic;               /* written last: a torn record has no magic */
} meta_t;

/* ---- images --------------------------------------------------------------- */

#ifndef BUG_TRUST_HEADER
static uint32_t crc32(const uint8_t *p, uint32_t n)
{
    uint32_t c = 0xFFFFFFFFu;
    while (n--) {
        c ^= *p++;
        for (int k = 0; k < 8; k++)
            c = (c >> 1) ^ (0xEDB88320u & -(c & 1u));
    }
    return ~c;
}
#endif

static const img_hdr_t *hdr(uint32_t slot)
{
    return (const img_hdr_t *)slot;
}

static int image_valid(uint32_t slot)
{
    const img_hdr_t *h = hdr(slot);
    if (h->magic != IMG_MAGIC || h->size == 0 || h->size > SLOT_SIZE - IMG_OFFSET)
        return 0;
#ifdef BUG_TRUST_HEADER
    return 1;
#else
    return crc32((const uint8_t *)(slot + IMG_OFFSET), h->size) == h->crc;
#endif
}

static int same_image(uint32_t a, uint32_t b)
{
    return hdr(a)->version == hdr(b)->version && hdr(a)->crc == hdr(b)->crc;
}

/* Clear Slot B's magic. Programming zeros over written flash is allowed on both
 * chips, so this is cheap and needs no erase. */
static void consume_staging(void)
{
    flash_word(SLOT_B, 0);
}

/* ---- rollback floor ------------------------------------------------------- */

static const meta_t *meta(uint32_t page)
{
    const meta_t *m = (const meta_t *)page;
    return m->magic == META_MAGIC ? m : 0;
}

#ifndef BUG_NAIVE_FLOOR

/* Two pages; the newer valid record wins. A rewrite always goes to the page
 * that does NOT hold the current record, so a cut leaves the old one intact. */
static uint32_t meta_floor(void)
{
    const meta_t *m0 = meta(META_0), *m1 = meta(META_1);
    if (m0 && m1)
        return (m0->seq > m1->seq ? m0 : m1)->floor;
    return m0 ? m0->floor : m1 ? m1->floor : 0;
}

static void meta_write(uint32_t floor)
{
    const meta_t *m0 = meta(META_0), *m1 = meta(META_1);
    uint32_t seq = 0, target = META_0;
    if (m0 && (!m1 || m0->seq > m1->seq)) {
        seq = m0->seq;
        target = META_1;
    } else if (m1) {
        seq = m1->seq;
    }
    flash_erase(target, 1);
    flash_word(target + 0, seq + 1);
    flash_word(target + 4, floor);
    flash_word(target + 8, META_MAGIC);
}

#else

static uint32_t meta_floor(void)
{
    const meta_t *m = meta(META_0);
    return m ? m->floor : 0;
}

static void meta_write(uint32_t floor)
{
    flash_erase(META_0, 1);
    flash_word(META_0 + 0, 1);
    flash_word(META_0 + 4, floor);
    flash_word(META_0 + 8, META_MAGIC);
}

#endif

/* ---- install -------------------------------------------------------------- */

/* One program per cell: a halfword on the F1, a word on the F4. */
static void copy_cells(uint32_t dst, uint32_t src, uint32_t n)
{
#if defined(HOLD_PG)
    flash_pg(1);
    for (uint32_t i = 0; i < n; i += CELL) {
        wdg_feed();
        *(volatile cell_t *)(dst + i) = *(const cell_t *)(src + i);
        flash_wait();
    }
    flash_pg(0);
#elif defined(BUG_EARLY_UNPG)
    for (uint32_t i = 0; i < n; i += 2 * CELL) {
        wdg_feed();
        flash_cell(dst + i, *(const cell_t *)(src + i));
        if (i + CELL < n)                 /* PG is clear again by now */
            *(volatile cell_t *)(dst + i + CELL) = *(const cell_t *)(src + i + CELL);
    }
#else
    for (uint32_t i = 0; i < n; i += CELL) {
        wdg_feed();
#ifdef BUG_RESUME_COPY
        if (*(const cell_t *)(dst + i) == *(const cell_t *)(src + i))
            continue;                     /* already there from the interrupted attempt */
#endif
        flash_cell(dst + i, *(const cell_t *)(src + i));
    }
#endif
}

static void install(void)
{
    uint32_t version = hdr(SLOT_B)->version;
    uint32_t body = (hdr(SLOT_B)->size + CELL - 1u) & ~(CELL - 1u);

    uart_puts("BL: installing\r\n");
#ifndef BUG_WATCHDOG
    wdg_stretch();                        /* the erases ahead outlast the reset timeout */
#endif
    wdg_feed();
#ifdef BUG_RESUME_COPY
    /* The floor already names this version and Slot A has no header: an install was
     * interrupted after its erase. Carry on from there instead of starting over. */
    int resume = meta_floor() == version && hdr(SLOT_A)->magic == 0xFFFFFFFFu;
#endif
#ifndef BUG_NO_UNLOCK
    flash_unlock();
#endif
#ifdef BUG_SELF_LOCK
    lock_bootloader();
#endif
#ifdef BUG_RETRY_LIMIT
    /* Count install attempts with two marks in the staged image's unused header
     * area, so a bad image cannot keep the device rebooting for ever. Two attempts
     * already started and not finished: give up on this update. */
    const volatile cell_t *tries = (const volatile cell_t *)(SLOT_B + 0x10);
    if (tries[0] == 0 && tries[1] == 0) {
        uart_puts("BL: giving up on this update\r\n");
        consume_staging();
        flash_lock();
        return;
    }
    flash_cell(SLOT_B + 0x10 + (tries[0] ? 0 : CELL), 0);
#endif
#ifndef BUG_NAIVE_FLOOR
    meta_write(version);
#endif
#ifdef BUG_CONSUME_FIRST
    img_hdr_t h = *hdr(SLOT_B);           /* keep a RAM copy, Slot B is about to lose it */
    consume_staging();
#endif
#ifndef BUG_NO_ERASE
#ifdef BUG_RESUME_COPY
    if (!resume)
#endif
    flash_erase(SLOT_A, IMG_OFFSET + body);
#endif
#ifdef BUG_TRUST_HEADER
    copy_cells(SLOT_A, SLOT_B, sizeof(img_hdr_t));
#endif
    copy_cells(SLOT_A + IMG_OFFSET, SLOT_B + IMG_OFFSET, body);
#if defined(BUG_CONSUME_FIRST)
    copy_cells(SLOT_A, (uint32_t)&h, sizeof(img_hdr_t));
#elif !defined(BUG_TRUST_HEADER)
    copy_cells(SLOT_A, SLOT_B, sizeof(img_hdr_t));
#endif
#ifndef BUG_CONSUME_FIRST
    consume_staging();
#endif
#ifdef BUG_NAIVE_FLOOR
    meta_write(version);
#endif
    flash_lock();
}

/* ---- boot ----------------------------------------------------------------- */

/* Switch to the app's stack and go. Naked, so the compiler adds nothing around the
 * two instructions: once MSP has moved, anything that still uses the old frame
 * (a saved-register pop, a tail-call epilogue) reads from the wrong stack. */
__attribute__((naked, noreturn)) static void switch_stack_and_go(uint32_t sp, uint32_t pc)
{
    (void)sp;
    (void)pc;
#ifdef BUG_POP_AFTER_SWITCH
    /* what an optimised tail call did in the other bootloader: restore the caller's
     * registers after the switch, from the new stack. The app's stack starts at the
     * very top of RAM, so this reads past the end of it. */
    __asm volatile("push {r4, lr}\n msr msp, r0\n pop {r4, lr}\n bx r1");
#else
    __asm volatile("msr msp, r0\n bx r1");
#endif
}

static void jump(uint32_t slot)
{
    const uint32_t *vt = (const uint32_t *)(slot + IMG_OFFSET);
    SCB_VTOR = (uint32_t)vt;
    switch_stack_and_go(vt[0], vt[1]);
}

int main(void)
{
    uart_init();
    uart_puts("BL\r\n");
    uint32_t floor = meta_floor();

    if (image_valid(SLOT_B)) {
        if (image_valid(SLOT_A) && same_image(SLOT_A, SLOT_B)) {
            flash_unlock();               /* cut after the copy, before step 5 */
            consume_staging();
            flash_lock();
        } else if (hdr(SLOT_B)->version >= floor) {
            install();
            floor = meta_floor();
        } else {
            uart_puts("BL: rejected old image\r\n");
        }
    }

    if (image_valid(SLOT_A) && hdr(SLOT_A)->version >= floor)
        jump(SLOT_A);

    uart_puts("BL: no bootable image\r\n");
    for (;;)
        ;
}
