"""Record what the torn-write test firmware prints, into torn_results.txt.

    pip install pyserial
    python capture.py COM5          (the Nucleo's ST-LINK port; see Device Manager)

Start this first, then press the black reset button on the board. It stops at DONE.
"""
import sys
import time

import serial

port = sys.argv[1]
out = open("torn_results.txt", "w")
with serial.Serial(port, 115200, timeout=1) as s:
    print("listening on %s; press the black reset button on the board" % port)
    started, last = False, time.time()
    while True:
        line = s.readline().decode(errors="replace").strip()
        if not line:
            if started and time.time() - last > 30:
                print("nothing for 30 s; stopping. Send torn_results.txt anyway.")
                break
            continue
        last = time.time()
        if line.startswith("TORN"):
            started = True
            out.seek(0)
            out.truncate()
        if started:
            out.write(line + "\n")
            out.flush()
            print(line)
        if line == "DONE":
            print("finished: send torn_results.txt")
            break
