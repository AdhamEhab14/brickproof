#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

int main(void)
{
	for (;;) {
		printk("APP v%d\n", APP_VERSION);
		k_msleep(200);
	}
	return 0;
}
