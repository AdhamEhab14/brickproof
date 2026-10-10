/* BrickProof demo bootloader: overwrite-style A/B update with a rollback floor.
 *
 * A new image is dropped into Slot B (by an OTA agent, a debugger, BrickProof).
 * On the next boot this copies it over Slot A and runs it. The order of the
 * install is what makes it survive a power cut at any flash operation:
 *
 *   1. raise the rollback floor to the new version (two-page record, see meta_write)
 *   2. erase Slot A
 *   3. copy the app body
 *   4. copy the header last, so Slot A only looks valid once it is complete
 *   5. mark Slot B consumed
 *
 * Until step 5, Slot B is still a valid image, so a cut anywhere earlier just
 * means the next boot runs the install again.
 *
 * Three build options put back real bugs found by BrickProof in another
 * bootloader. Each one should make at least one cut fail:
 *   BUG_CONSUME_FIRST  mark Slot B consumed before copying (cut = no image left)
 *   BUG_TRUST_HEADER   copy the header first and check only its magic, not the CRC
 *                      (cut = a half-copied image that looks valid)
 *   BUG_NAIVE_FLOOR    keep the floor in one page, erase it and rewrite it after
 *                      the install (cut = floor back to 0, old images accepted again)
 */
#include "demo.h"

#define FLASH_KEYR  REG(0x40022004u)
#define FLASH_SR    REG(0x4002200Cu)
#define FLASH_CR    REG(0x40022010u)
#define FLASH_AR    REG(0x40022014u)
#define CR_PG       (1u << 0)
#define CR_PER      (1u << 1)
#define CR_STRT     (1u << 6)
#define CR_LOCK     (1u << 7)
#define SR_BSY      (1u << 0)

#define META_MAGIC  0x4D455441u   /* "ATEM" */

typedef struct {
    uint32_t seq;
    uint32_t floor;
    uint32_t magic;               /* written last: a torn record has no magic */
} meta_t;

/* ---- flash ---------------------------------------------------------------- */

static void flash_wait(void)
{
    while (FLASH_SR & SR_BSY)
        ;
}

static void flash_unlock(void)
{
    FLASH_KEYR = 0x45670123u;
    FLASH_KEYR = 0xCDEF89ABu;
}

static void flash_erase(uint32_t page)
{
    FLASH_CR |= CR_PER;
    FLASH_AR = page;
    FLASH_CR |= CR_STRT;
    flash_wait();
    FLASH_CR &= ~CR_PER;
}

static void flash_half(uint32_t addr, uint16_t v)
{
    FLASH_CR |= CR_PG;
    *(volatile uint16_t *)addr = v;
    flash_wait();
    FLASH_CR &= ~CR_PG;
}

static void flash_word(uint32_t addr, uint32_t v)
{
    flash_half(addr, (uint16_t)v);
    flash_half(addr + 2, (uint16_t)(v >> 16));
}

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

/* Clear Slot B's magic. Programming 0x0000 over a written halfword is allowed
 * on the F1, so this is one cheap operation and needs no erase. */
static void consume_staging(void)
{
    flash_half(SLOT_B, 0);
    flash_half(SLOT_B + 2, 0);
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
    flash_erase(target);
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
    flash_erase(META_0);
    flash_word(META_0 + 0, 1);
    flash_word(META_0 + 4, floor);
    flash_word(META_0 + 8, META_MAGIC);
}

#endif

/* ---- install -------------------------------------------------------------- */

static void copy_halfwords(uint32_t dst, uint32_t src, uint32_t n)
{
    for (uint32_t i = 0; i < n; i += 2)
        flash_half(dst + i, *(const uint16_t *)(src + i));
}

static void install(void)
{
    uint32_t version = hdr(SLOT_B)->version;
    uint32_t body = (hdr(SLOT_B)->size + 1u) & ~1u;
    uint32_t pages = (IMG_OFFSET + body + PAGE_SIZE - 1) / PAGE_SIZE;

    uart_puts("BL: installing\r\n");
    flash_unlock();
#ifndef BUG_NAIVE_FLOOR
    meta_write(version);
#endif
#ifdef BUG_CONSUME_FIRST
    img_hdr_t h = *hdr(SLOT_B);           /* keep a RAM copy, Slot B is about to lose it */
    consume_staging();
#endif
    for (uint32_t p = 0; p < pages; p++)
        flash_erase(SLOT_A + p * PAGE_SIZE);
#ifdef BUG_TRUST_HEADER
    copy_halfwords(SLOT_A, SLOT_B, sizeof(img_hdr_t));
#endif
    copy_halfwords(SLOT_A + IMG_OFFSET, SLOT_B + IMG_OFFSET, body);
#if defined(BUG_CONSUME_FIRST)
    copy_halfwords(SLOT_A, (uint32_t)&h, sizeof(img_hdr_t));
#elif !defined(BUG_TRUST_HEADER)
    copy_halfwords(SLOT_A, SLOT_B, sizeof(img_hdr_t));
#endif
#ifndef BUG_CONSUME_FIRST
    consume_staging();
#endif
#ifdef BUG_NAIVE_FLOOR
    meta_write(version);
#endif
    FLASH_CR |= CR_LOCK;
}

/* ---- boot ----------------------------------------------------------------- */

static void jump(uint32_t slot)
{
    const uint32_t *vt = (const uint32_t *)(slot + IMG_OFFSET);
    SCB_VTOR = (uint32_t)vt;
    __asm volatile("msr msp, %0\n bx %1" : : "r"(vt[0]), "r"(vt[1]));
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
            FLASH_CR |= CR_LOCK;
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
