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
 *   BUG_NWRITE            (nRF52840 only) record the install's progress by clearing one
 *                         more bit of the same word after each step. Fine on an STM32F4,
 *                         which lets a word be programmed again and again. The nRF52
 *                         allows two writes to a word between erases, and the third
 *                         one is outside what the chip guarantees.
 *   BUG_BOOT_LOOP         (nRF52840 only) when a cut has left the install complete but
 *                         Slot B not yet consumed, give the image a trial boot: start the
 *                         watchdog with a reload register of its own, which a healthy new
 *                         image feeds and then consumes Slot B. This app was built before
 *                         that and feeds only the usual one, so half a second in the
 *                         watchdog resets it, Slot B is still there, and the next boot does
 *                         the same. Every boot prints the app's banner: only a look longer
 *                         than one boot shows the loop.
 *
 * EXT_FLASH (STM32F411 only) is not a bug either: the new image waits in an external SPI
 * NOR flash chip, and the rollback floor is kept there too.
 *
 * EEPROM_FLOOR (STM32F411 only, not a bug) keeps the rollback floor in an I2C EEPROM.
 * BUG_EE_NO_INVALIDATE with it rewrites a record without clearing its old magic first.
 *
 * On the STM32L4 (-DSTM32L4) every double word has ECC, and a program or erase cut short
 * can leave it wrong: reading it raises an NMI. The bootloader catches that, and treats
 * whatever it was reading as invalid. BUG_NO_ECC_NMI leaves the NMI to the default
 * handler, which hangs.
 *
 * STANDBY_PAUSE (STM32F1 and F4, not a bug) pauses an install once in Standby, as a device on
 * a supercap does to let it recharge, and carries on after the wake. Standby loses RAM: the
 * wake is a reset, so the bootloader asks PWR's SBF whether it has already paused.
 * BUG_STANDBY_RAM keeps that in a RAM variable start-up leaves alone instead, which the chip
 * does not keep through Standby: it pauses for ever.
 *
 * HOLD_PG is not a bug: it is the other common way to write flash, with PG left set
 * over a whole run of cells. A power cut can fall between any two of them.
 *
 * The same source builds for an STM32F103, with -DSTM32F4 for an STM32F411, -DSTM32L4 for
 * an STM32L476, -DSTM32H5 for an STM32H563 and -DNRF52 for an nRF52840. What differs
 * between them (the flash map, how to erase and program, the option bytes) is in
 * common/chip_*.h. On the H563 a cell is a 128-bit word that is never programmed twice
 * (CELL_IS_BLOCK): Slot B is marked consumed with a cell of its own, and the floor record
 * is one cell.
 */
#include "demo.h"

#define META_MAGIC  0x4D455441u   /* "ATEM" */

typedef struct {
    uint32_t seq;
    uint32_t floor;
    uint32_t magic;               /* written last: a torn record has no magic */
} meta_t;

#if defined(EEPROM_FLOOR) || defined(STM32L4)
static meta_t meta_copy[2];
#endif

#ifdef STM32L4
volatile int ecc_error;

#ifndef BUG_NO_ECC_NMI
/* A read hit a double word whose ECC is wrong: the data that came back is not to be
 * trusted. Note it for the code that did the reading, and carry on. */
void NMI_Handler(void)
{
    if (FLASH_ECCR & ECCR_ECCD) {
        FLASH_ECCR = ECCR_ECCD;
        ecc_error = 1;
    }
}
#endif
#endif

#ifdef EXT_FLASH
/* With an external flash chip the staged image is read into RAM once at start-up, and
 * everything that looks at "Slot B" looks at that copy. */
static uint32_t staged[STAGED_MAX / 4];
static meta_t meta_copy[2];
#define SLOT_B ((uint32_t)staged)
#endif

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

static int image_check(uint32_t slot)
{
    const img_hdr_t *h = hdr(slot);
    if (h->magic != IMG_MAGIC || h->size == 0 || h->size > SLOT_SIZE - IMG_OFFSET)
        return 0;
#ifdef CELL_IS_BLOCK
    if (slot == SLOT_B && !cell_erased((const volatile cell_t *)CONSUMED))
        return 0;                         /* consumed: see consume_staging */
#endif
#ifdef EXT_FLASH
    if (slot == SLOT_B && h->size > STAGED_MAX - IMG_OFFSET)
        return 0;                         /* more than was read from the chip */
#endif
#ifdef BUG_TRUST_HEADER
    return 1;
#else
    return crc32((const uint8_t *)(slot + IMG_OFFSET), h->size) == h->crc;
#endif
}

/* Valid, and nothing read on the way hit an ECC error. */
static int image_valid(uint32_t slot)
{
    ecc_clear();
    int ok = image_check(slot);
    return ok && !ecc_seen();
}

static int same_image(uint32_t a, uint32_t b)
{
    return hdr(a)->version == hdr(b)->version && hdr(a)->crc == hdr(b)->crc;
}

/* Clear Slot B's magic. Programming zeros over written flash is allowed on the F1
 * and the F4, so this is cheap and needs no erase. The H563 does not program a cell
 * twice, so there Slot B gets a consumed marker in a cell of its own. */
static void consume_staging(void)
{
#if defined(EXT_FLASH)
    staged[0] = 0;
    ext_program(EXT_STAGING, &staged[0], 4);
#elif defined(STM32L4)
    flash_cell(SLOT_B, 0);                /* all zeros: the one value a written cell takes */
#elif defined(CELL_IS_BLOCK)
    flash_cell(CONSUMED, CELL_ZERO);
#else
    flash_word(SLOT_B, 0);
#endif
}

/* ---- rollback floor ------------------------------------------------------- */

static const meta_t *meta(uint32_t page)
{
#if defined(EXT_FLASH)
    meta_t *m = &meta_copy[page == META_1];
    ext_read(page, m, sizeof *m);
#elif defined(EEPROM_FLOOR)
    meta_t *m = &meta_copy[page == META_1];
    ee_read(page, m, sizeof *m);
#elif defined(STM32L4)
    meta_t *m = &meta_copy[page == META_1];
    ecc_clear();
    *m = *(const meta_t *)page;
    if (ecc_seen())
        return 0;                         /* a page whose erase or program was cut short */
#else
    const meta_t *m = (const meta_t *)page;
#endif
    return m->magic == META_MAGIC ? m : 0;
}

static void meta_store(uint32_t target, uint32_t seq, uint32_t floor)
{
#ifdef EXT_FLASH
    /* the magic goes in with a program of its own, after the rest: a page program
     * that is cut short must not leave a record that looks complete */
    uint32_t record[2] = { seq, floor }, magic = META_MAGIC;
    ext_erase_sector(target);
    ext_program(target, record, sizeof record);
    ext_program(target + 8, &magic, sizeof magic);
#elif defined(EEPROM_FLOOR)
    uint32_t record[3] = { seq, floor, META_MAGIC };
    /* An EEPROM needs no erase, so the page may still hold an older record with a valid
     * magic. Clear that first: a write cut short can leave anything in seq and floor, and
     * the old magic would vouch for it. Then the record, then the magic. */
#ifndef BUG_EE_NO_INVALIDATE
    uint32_t none = 0;
    ee_write(target + 8, &none, sizeof none);
#endif
    ee_write(target, record, 8);
    ee_write(target + 8, &record[2], 4);
#elif defined(STM32L4)
    /* two double words, each programmed once: seq and floor, then the magic */
    flash_erase(target, 1);
    flash_cell(target, ((uint64_t)floor << 32) | seq);
    flash_cell(target + 8, 0xFFFFFFFF00000000ull | META_MAGIC);
#elif defined(CELL_IS_BLOCK)
    /* the whole record is one cell: one program, all of it or none */
    flash_erase(target, 1);
    flash_cell(target, (cell_t){{seq, floor, META_MAGIC, 0xFFFFFFFFu}});
#else
    flash_erase(target, 1);
    flash_word(target + 0, seq);
    flash_word(target + 4, floor);
    flash_word(target + 8, META_MAGIC);
#endif
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
    meta_store(target, seq + 1, floor);
}

#else

static uint32_t meta_floor(void)
{
    const meta_t *m = meta(META_0);
    return m ? m->floor : 0;
}

static void meta_write(uint32_t floor)
{
    meta_store(META_0, 1, floor);
}

#endif

/* ---- install -------------------------------------------------------------- */

#ifdef STANDBY_PAUSE
#define PWR_CR         REG(0x40007000u)
#define PWR_CSR        REG(0x40007004u)
#define SCB_SCR        REG(0xE000ED10u)
#define PWR_CR_PDDS    (1u << 1)
#define PWR_CR_CWUF    (1u << 2)
#define PWR_CR_CSBF    (1u << 3)
#define PWR_CSR_SBF    (1u << 1)
#define PAUSED         0x50415553u   /* "PAUS" */

#ifdef BUG_STANDBY_RAM
__attribute__((section(".noinit"))) static uint32_t paused;
#endif

/* Pause once in Standby. The wake is a reset: main() starts over and finds the install to do. */
static void pause_in_standby(void)
{
#ifdef BUG_STANDBY_RAM
    if (paused == PAUSED)
        return;
    paused = PAUSED;
#else
    if (PWR_CSR & PWR_CSR_SBF)
        return;                           /* this boot is the wake: carry on */
#endif
    RCC_APB1ENR |= (1u << 28);            /* PWR */
    PWR_CR |= PWR_CR_CWUF | PWR_CR_PDDS;
    SCB_SCR |= (1u << 2);                 /* SLEEPDEEP */
    __asm volatile("dsb\n wfi");
    for (;;)
        ;
}

/* The install is done: the next one may pause again. */
static void standby_done(void)
{
#ifndef BUG_STANDBY_RAM
    PWR_CR |= PWR_CR_CSBF;
#endif
}
#else
#define pause_in_standby() ((void)0)
#define standby_done() ((void)0)
#endif

#ifdef BUG_NWRITE
/* One bit per step, cleared in the staged image's unused header area. */
static void progress(uint32_t step)
{
    flash_word(SLOT_B + 0x14, ~((2u << step) - 1u));
}
#else
#define progress(step) ((void)0)
#endif

/* One program per cell: a halfword on the F1, a word on the F4. */
static void copy_cells(uint32_t dst, uint32_t src, uint32_t n)
{
#if defined(HOLD_PG)
    flash_pg(1);
    for (uint32_t i = 0; i < n; i += CELL) {
        wdg_feed();
#ifdef CELL_IS_BLOCK
        cell_store(dst + i, (const cell_t *)(src + i));
#else
        *(volatile cell_t *)(dst + i) = *(const cell_t *)(src + i);
#endif
        flash_wait();
    }
    flash_pg(0);
#elif defined(BUG_EARLY_UNPG)
    for (uint32_t i = 0; i < n; i += 2 * CELL) {
        wdg_feed();
        flash_cell(dst + i, *(const cell_t *)(src + i));
        if (i + CELL < n)                 /* PG is clear again by now */
#ifdef CELL_IS_BLOCK
            cell_store(dst + i + CELL, (const cell_t *)(src + i + CELL));
#else
            *(volatile cell_t *)(dst + i + CELL) = *(const cell_t *)(src + i + CELL);
#endif
    }
#else
    for (uint32_t i = 0; i < n; i += CELL) {
        wdg_feed();
#ifdef BUG_RESUME_COPY
#ifdef CELL_IS_BLOCK
        if (cell_same((const cell_t *)(dst + i), (const cell_t *)(src + i)))
#else
        if (*(const cell_t *)(dst + i) == *(const cell_t *)(src + i))
#endif
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
#ifdef CELL_IS_BLOCK
    if (cell_clear(&tries[0]) && cell_clear(&tries[1])) {
#else
    if (tries[0] == 0 && tries[1] == 0) {
#endif
        uart_puts("BL: giving up on this update\r\n");
        consume_staging();
        flash_lock();
        return;
    }
#ifdef CELL_IS_BLOCK
    flash_cell(SLOT_B + 0x10 + (cell_clear(&tries[0]) ? CELL : 0), CELL_ZERO);
#else
    flash_cell(SLOT_B + 0x10 + (tries[0] ? 0 : CELL), 0);
#endif
#endif
#ifndef BUG_NAIVE_FLOOR
    meta_write(version);
#endif
    progress(0);
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
    pause_in_standby();                   /* Slot A erased: the worst moment for it */
    progress(1);
#ifdef BUG_TRUST_HEADER
    copy_cells(SLOT_A, SLOT_B, sizeof(img_hdr_t));
#endif
    copy_cells(SLOT_A + IMG_OFFSET, SLOT_B + IMG_OFFSET, body);
    progress(2);
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
    standby_done();
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

#ifdef BUG_BOOT_LOOP
#ifndef NRF52
#error "BUG_BOOT_LOOP is written for the nRF52840 watchdog"
#endif
/* Start the watchdog for the image's first run. It wants RR[1] as well as RR[0] before it
 * reloads, and cannot be stopped or changed once it runs. */
static void trial_boot(void)
{
    REG(0x40010504u) = 16384u;            /* CRV: half a second of the 32.768 kHz clock */
    REG(0x40010508u) = 3u;                /* RREN: RR[0] and RR[1] */
    REG(0x40010000u) = 1u;                /* TASKS_START */
    uart_puts("BL: trial boot\r\n");
}
#endif

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
#ifdef EXT_FLASH
    ext_init();
    ext_read(EXT_STAGING, staged, sizeof staged);
#endif
#ifdef EEPROM_FLOOR
    ee_init();
#endif
    uint32_t floor = meta_floor();

    if (image_valid(SLOT_B)) {
        if (image_valid(SLOT_A) && same_image(SLOT_A, SLOT_B)) {
#ifdef BUG_BOOT_LOOP
            trial_boot();                 /* Slot B is left for the image to consume */
#else
            flash_unlock();               /* cut after the copy, before step 5 */
            consume_staging();
            flash_lock();
#endif
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
