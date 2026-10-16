/* A storage workload for BrickProof's `storage` driver: one store (Zephyr NVS, ZMS, settings
 * on FCB, or littlefs, chosen at build time) on the board's storage partition, driven over
 * the console UART.
 *
 * Every boot mounts the store and prints what it holds:
 *
 *   STORE <nvs|littlefs>
 *   MOUNT ok | MOUNT formatted | MOUNT err <rc>
 *   R <key> <gen> | R <key> - | R <key> bad | R <key> err <rc>     one line per key
 *   READY
 *
 * then waits for a command, one character:
 *
 *   S  run the next step of the workload:  C <step> W <key> <gen> | C <step> D <key>
 *      when it returned, E <step> <rc> if it failed, Z when there are no more steps
 *   W  run every remaining step the same way, then W end
 *   P  write the probe key with generation 9999 and read it back: P ok | P err <rc>
 *
 * A value is <key, gen, length> and a payload made from them, so a read can tell a
 * whole value from a half-written or mixed-up one ("bad"). The workload writes and
 * deletes keys 1..8 in a fixed order, enough to make the store reclaim space more than
 * once. The driver learns where each step starts and ends in flash operations, and
 * after a power cut checks the store against the steps that had finished.
 */
#include <errno.h>
#include <string.h>
#include <zephyr/device.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/printk.h>

#define KEYS      8
#define PROBE_KEY 9
#define PROBE_GEN 9999u
#define STEPS     80
#define HDR       12u
#define MAX_LEN   (HDR + 200u)

#define STORAGE_ID     FIXED_PARTITION_ID(storage_partition)
#define STORAGE_OFFSET FIXED_PARTITION_OFFSET(storage_partition)
#define STORAGE_SIZE   FIXED_PARTITION_SIZE(storage_partition)

static uint8_t buf[MAX_LEN];

/* ---- values -------------------------------------------------------------------- */

static uint32_t value_len(uint32_t key, uint32_t gen)
{
	return HDR + 4u + (key * 37u + gen * 11u) % 180u;
}

static uint8_t payload(uint32_t key, uint32_t gen, uint32_t i)
{
	return (uint8_t)(key * 31u + gen * 7u + i * 13u);
}

static uint32_t make_value(uint8_t *b, uint32_t key, uint32_t gen)
{
	uint32_t len = value_len(key, gen);

	memcpy(b, &key, 4);
	memcpy(b + 4, &gen, 4);
	memcpy(b + 8, &len, 4);
	for (uint32_t i = HDR; i < len; i++) {
		b[i] = payload(key, gen, i);
	}
	return len;
}

/* The generation a whole, right value holds, or -1. */
static int32_t value_gen(const uint8_t *b, int n, uint32_t key)
{
	uint32_t k, gen, len;

	if (n < (int)HDR) {
		return -1;
	}
	memcpy(&k, b, 4);
	memcpy(&gen, b + 4, 4);
	memcpy(&len, b + 8, 4);
	if (k != key || len != (uint32_t)n || len != value_len(key, gen)) {
		return -1;
	}
	for (uint32_t i = HDR; i < len; i++) {
		if (b[i] != payload(key, gen, i)) {
			return -1;
		}
	}
	return (int32_t)gen;
}

/* ---- the store -------------------------------------------------------------------- */

#if defined(CONFIG_NVS)
#include <zephyr/fs/nvs.h>

#define BACKEND "nvs"
static struct nvs_fs nvs;

static int store_mount(const char **how)
{
	struct flash_pages_info info;
	int rc;

	nvs.flash_device = FIXED_PARTITION_DEVICE(storage_partition);
	nvs.offset = STORAGE_OFFSET;
	rc = flash_get_page_info_by_offs(nvs.flash_device, nvs.offset, &info);
	if (rc) {
		return rc;
	}
	nvs.sector_size = info.size;
	nvs.sector_count = 3;           /* small, so the workload makes it reclaim space */
	*how = "ok";
	return nvs_mount(&nvs);
}

static int store_write(uint32_t key, const uint8_t *b, uint32_t len)
{
	int rc = nvs_write(&nvs, (uint16_t)key, b, len);

	return rc < 0 ? rc : 0;
}

static int store_read(uint32_t key, uint8_t *b, uint32_t max)
{
	int rc = nvs_read(&nvs, (uint16_t)key, b, max);

	return rc > (int)max ? (int)max + 1 : rc;   /* longer than any value: not ours */
}

static int store_delete(uint32_t key)
{
	return nvs_delete(&nvs, (uint16_t)key);
}

#elif defined(CONFIG_ZMS)
#include <zephyr/fs/zms.h>

#define BACKEND "zms"
static struct zms_fs zms;

static int store_mount(const char **how)
{
	struct flash_pages_info info;
	int rc;

	zms.flash_device = FIXED_PARTITION_DEVICE(storage_partition);
	zms.offset = STORAGE_OFFSET;
	rc = flash_get_page_info_by_offs(zms.flash_device, zms.offset, &info);
	if (rc) {
		return rc;
	}
	zms.sector_size = info.size;
	zms.sector_count = 3;           /* small, so the workload makes it reclaim space */
	*how = "ok";
	return zms_mount(&zms);
}

static int store_write(uint32_t key, const uint8_t *b, uint32_t len)
{
	ssize_t rc = zms_write(&zms, key, b, len);

	return rc < 0 ? (int)rc : 0;
}

static int store_read(uint32_t key, uint8_t *b, uint32_t max)
{
	ssize_t len = zms_get_data_length(&zms, key);

	if (len < 0) {
		return (int)len;
	}
	if (len > (ssize_t)max) {
		return (int)max + 1;        /* longer than any value: not ours */
	}
	return (int)zms_read(&zms, key, b, len);
}

static int store_delete(uint32_t key)
{
	return zms_delete(&zms, key);
}

#elif defined(CONFIG_SETTINGS_FCB)
#include <stdio.h>
#include <zephyr/settings/settings.h>

/* Zephyr's settings subsystem on its FCB backend: each save appends an entry to the
 * flash circular buffer. A value is the whole setting "bp/k<key>". */
#define BACKEND "settings_fcb"

struct load_ctx {
	uint8_t *b;
	uint32_t max;
	int len;
};

static int load_one(const char *key, size_t len, settings_read_cb read_cb, void *cb_arg,
		    void *param)
{
	struct load_ctx *ctx = param;

	if (key != NULL && key[0] != '\0') {
		return 0;                   /* a longer name under this one */
	}
	if (len > ctx->max) {
		ctx->len = (int)ctx->max + 1;
		return 0;
	}
	ctx->len = (int)read_cb(cb_arg, ctx->b, len);
	return 0;
}

static void name_of(char *p, uint32_t key)
{
	snprintf(p, 16, "bp/k%u", (unsigned int)key);
}

static int store_mount(const char **how)
{
	*how = "ok";
	return settings_subsys_init();
}

static int store_write(uint32_t key, const uint8_t *b, uint32_t len)
{
	char p[16];

	name_of(p, key);
	return settings_save_one(p, b, len);
}

static int store_read(uint32_t key, uint8_t *b, uint32_t max)
{
	struct load_ctx ctx = {.b = b, .max = max, .len = -ENOENT};
	char p[16];
	int rc;

	name_of(p, key);
	rc = settings_load_subtree_direct(p, load_one, &ctx);
	if (rc) {
		return rc;
	}
	return ctx.len == 0 ? -ENOENT : ctx.len;    /* a delete is saved as an empty value */
}

static int store_delete(uint32_t key)
{
	char p[16];

	name_of(p, key);
	return settings_delete(p);
}

#elif defined(CONFIG_FILE_SYSTEM_LITTLEFS)
#include <stdio.h>
#include <zephyr/fs/fs.h>
#include <zephyr/fs/littlefs.h>

#define BACKEND "littlefs"
FS_LITTLEFS_DECLARE_DEFAULT_CONFIG(lfs_data);
static struct fs_mount_t lfs_mnt = {
	.type = FS_LITTLEFS,
	.fs_data = &lfs_data,
	.storage_dev = (void *)STORAGE_ID,
	.mnt_point = "/lfs",
	.flags = FS_MOUNT_FLAG_NO_FORMAT,
};

static void path_of(char *p, uint32_t key)
{
	snprintf(p, 16, "/lfs/k%u", (unsigned int)key);
}

/* The store is formatted only when the partition is blank, on the first boot. A
 * partition that holds something and does not mount is reported, never wiped. */
static bool partition_blank(void)
{
	const struct flash_area *fa;
	uint8_t chunk[64];
	bool blank = true;

	if (flash_area_open(STORAGE_ID, &fa)) {
		return false;
	}
	for (off_t off = 0; off < (off_t)fa->fa_size && blank; off += sizeof(chunk)) {
		if (flash_area_read(fa, off, chunk, sizeof(chunk))) {
			blank = false;
			break;
		}
		for (size_t i = 0; i < sizeof(chunk); i++) {
			if (chunk[i] != 0xFF) {
				blank = false;
				break;
			}
		}
	}
	flash_area_close(fa);
	return blank;
}

static int store_mount(const char **how)
{
	int rc = fs_mount(&lfs_mnt);

	*how = "ok";
	if (rc == 0 || !partition_blank()) {
		return rc;
	}
	rc = fs_mkfs(FS_LITTLEFS, (uintptr_t)STORAGE_ID, &lfs_data, 0);
	if (rc) {
		return rc;
	}
	*how = "formatted";
	return fs_mount(&lfs_mnt);
}

static int store_write(uint32_t key, const uint8_t *b, uint32_t len)
{
	struct fs_file_t f;
	char p[16];
	int rc, rc2;

	path_of(p, key);
	fs_file_t_init(&f);
	rc = fs_open(&f, p, FS_O_CREATE | FS_O_WRITE | FS_O_TRUNC);
	if (rc) {
		return rc;
	}
	rc = fs_write(&f, b, len);
	rc2 = fs_close(&f);             /* littlefs commits on close */
	if (rc < 0) {
		return rc;
	}
	if (rc != (int)len) {
		return -EIO;
	}
	return rc2;
}

static int store_read(uint32_t key, uint8_t *b, uint32_t max)
{
	struct fs_file_t f;
	char p[16];
	int rc;

	path_of(p, key);
	fs_file_t_init(&f);
	rc = fs_open(&f, p, FS_O_READ);
	if (rc) {
		return rc;
	}
	rc = fs_read(&f, b, max);
	if (rc == 0) {
		/* littlefs commits a file's creation when it is opened and its data on close,
		 * so a cut in between leaves it empty: no value yet, not a mangled one. A key
		 * that had a value and comes back empty still fails (its value is missing). */
		rc = -ENOENT;
	} else if (rc == (int)max) {
		uint8_t more;

		if (fs_read(&f, &more, 1) == 1) {
			rc = (int)max + 1;      /* longer than any value: not ours */
		}
	}
	fs_close(&f);
	return rc;
}

static int store_delete(uint32_t key)
{
	char p[16];

	path_of(p, key);
	return fs_unlink(p);
}

#else
#error "build with one of nvs.conf, zms.conf, settings_fcb.conf, littlefs.conf"
#endif

/* ---- the workload -------------------------------------------------------------------- */

static bool present[KEYS + 1];      /* what the workload has done so far, this boot */
static int next_step;

/* Step s: write key k (generation s + 1), or every ninth step delete one that is there. */
static int run_step(int s)
{
	uint32_t key = 1u + ((uint32_t)s * 5u) % KEYS;
	uint32_t gen = (uint32_t)s + 1u;
	uint32_t len;
	int rc;

	if (s % 9 == 8 && present[key]) {
		rc = store_delete(key);
		if (rc) {
			printk("E %d %d\n", s, rc);
			return rc;
		}
		present[key] = false;
		printk("C %d D %u\n", s, (unsigned int)key);
		return 0;
	}
	len = make_value(buf, key, gen);
	rc = store_write(key, buf, len);
	if (rc) {
		printk("E %d %d\n", s, rc);
		return rc;
	}
	present[key] = true;
	printk("C %d W %u %u\n", s, (unsigned int)key, (unsigned int)gen);
	return 0;
}

static void dump(void)
{
	for (uint32_t key = 1; key <= PROBE_KEY; key++) {
		int n = store_read(key, buf, MAX_LEN);

		if (n == -ENOENT) {
			printk("R %u -\n", (unsigned int)key);
		} else if (n < 0) {
			printk("R %u err %d\n", (unsigned int)key, n);
		} else {
			int32_t gen = value_gen(buf, n, key);

			if (gen < 0) {
				printk("R %u bad\n", (unsigned int)key);
			} else {
				printk("R %u %d\n", (unsigned int)key, (int)gen);
			}
		}
	}
}

static void probe(void)
{
	uint32_t len = make_value(buf, PROBE_KEY, PROBE_GEN);
	int rc = store_write(PROBE_KEY, buf, len);

	if (rc == 0) {
		int n = store_read(PROBE_KEY, buf, MAX_LEN);

		rc = value_gen(buf, n, PROBE_KEY) == (int32_t)PROBE_GEN ? 0 : (n < 0 ? n : -EBADMSG);
	}
	if (rc) {
		printk("P err %d\n", rc);
	} else {
		printk("P ok\n");
	}
}

int main(void)
{
	const struct device *uart = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));
	const char *how = "ok";
	int rc;

	printk("STORE %s\n", BACKEND);
	rc = store_mount(&how);
	if (rc) {
		printk("MOUNT err %d\n", rc);
		return 0;
	}
	printk("MOUNT %s\n", how);
	dump();
	printk("READY\n");

	for (;;) {
		unsigned char c;

		if (uart_poll_in(uart, &c) != 0) {
			k_msleep(1);
			continue;
		}
		if (c == 'S') {
			if (next_step >= STEPS) {
				printk("Z\n");
			} else if (run_step(next_step) == 0) {
				next_step++;
			}
		} else if (c == 'W') {
			while (next_step < STEPS && run_step(next_step) == 0) {
				next_step++;
			}
			printk("W end\n");
		} else if (c == 'P') {
			probe();
		}
	}
	return 0;
}
