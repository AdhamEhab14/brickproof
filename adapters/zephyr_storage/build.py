"""Build the storage workload (app/) for each store, for one board.

    python build.py <zephyr workspace> <output folder> [nrf52840]

The workspace is a `west init` / `west update` of Zephyr with the littlefs module in it.
The output folder is what `--target` points at: <store>.elf and <store>.bin for each store.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BOARDS = {"nrf52840": "nrf52840dk/nrf52840"}
STORES = ("nvs", "littlefs", "zms", "settings_fcb")


def main():
    ws, out = (os.path.abspath(a) for a in sys.argv[1:3])
    board = BOARDS[sys.argv[3] if len(sys.argv) > 3 else "nrf52840"]
    os.makedirs(out, exist_ok=True)
    for store in STORES:
        build = os.path.join(out, "build", store)
        subprocess.check_call(["west", "build", "-p", "-b", board, os.path.join(HERE, "app"),
                               "-d", build, "--", "-DEXTRA_CONF_FILE=%s.conf" % store], cwd=ws)
        for ext in ("elf", "bin"):
            shutil.copy(os.path.join(build, "zephyr", "zephyr." + ext),
                        os.path.join(out, "%s.%s" % (store, ext)))
    print("built into", out)


if __name__ == "__main__":
    main()
