"""Record labeled IMU data from MQTT to CSV files for training.

Subscribes to ME193/ceci/gait/raw (the format is described in simulator.py),
asks for the subject's name, then records one activity at a time.

Keys:
    0 standing   1 walking   2 running   3 biking   4 air-biking
    space  stop and save the current recording
    q      quit (saves the current recording first)
Pressing a number while recording saves the current recording and starts a new one.

Each recording is saved as data/raw/<subject>_<activity>_<timestamp>.csv with
columns t, ax, ay, az, gx, gy, gz, label, subject. The first and last 3 s are
trimmed off (getting into position / pressing the key).

Air-biking keeps its own label here. Training merges it into biking.

--sim saves to data/sim/ instead, with "_sim" in the filename. Use it whenever
simulator.py is the source. Training scripts only ever read data/raw/.

Usage:
    python laptop/logger.py
    python laptop/logger.py --sim
"""

import argparse
import collections
import csv
import json
import queue
import re
import select
import sys
import termios
import threading
import time
import tty
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORT = 1883
TOPIC = "ME193/ceci/gait/raw"
FS = 50
SAMPLE_MS = 1000 / FS
MIN_RATE_HZ = 45
RATE_WINDOW_S = 2.0      # rate is averaged over this long; messages carry 5 samples
TRIM_MS = 3000

REPO = Path(__file__).resolve().parent.parent
RAW_DIR = REPO / "data" / "raw"
SIM_DIR = REPO / "data" / "sim"

FIELDS = ["t", "ax", "ay", "az", "gx", "gy", "gz"]
LABELS = {"0": "standing", "1": "walking", "2": "running", "3": "biking", "4": "air-biking"}


class Recorder:
    """Receives samples on the MQTT thread; the main thread reads stats and saves."""

    def __init__(self):
        self.lock = threading.Lock()
        self.arrivals = collections.deque()  # wall time of each sample, for the rate
        self.first_arrival = None
        self.last_t = None
        self.missing = 0         # since the last status report
        self.restarts = 0        # t went backwards since the last status report
        self.bad = 0             # malformed messages since the last status report
        self.activity = None     # None = not recording
        self.rows = []
        self.rec_missing = 0
        self.rec_started = 0.0

    def on_message(self, client, userdata, msg):
        try:
            samples = json.loads(msg.payload)
            samples = [{k: s[k] for k in FIELDS} for s in samples]
        except (ValueError, TypeError, KeyError):
            with self.lock:
                self.bad += 1
            return
        now = time.monotonic()
        with self.lock:
            if self.first_arrival is None:
                self.first_arrival = now
            for s in samples:
                if self.last_t is not None:
                    dt = s["t"] - self.last_t
                    if dt <= 0:
                        self.restarts += 1
                    elif dt > 1.5 * SAMPLE_MS:
                        n = round(dt / SAMPLE_MS) - 1
                        self.missing += n
                        if self.activity:
                            self.rec_missing += n
                self.last_t = s["t"]
                self.arrivals.append(now)
                if self.activity:
                    self.rows.append(s)

    def start(self, activity):
        with self.lock:
            self.activity = activity
            self.rows = []
            self.rec_missing = 0
            self.rec_started = time.monotonic()

    def stop(self):
        """Stop recording and return (activity, rows, missing samples)."""
        with self.lock:
            out = (self.activity, self.rows, self.rec_missing)
            self.activity = None
            self.rows = []
            return out

    def report(self):
        """Return (rate Hz, missing, restarts, bad) and reset the counters.

        rate is None until the first full rate window after data starts.
        """
        now = time.monotonic()
        with self.lock:
            while self.arrivals and self.arrivals[0] < now - RATE_WINDOW_S:
                self.arrivals.popleft()
            if self.first_arrival is None or now - self.first_arrival < RATE_WINDOW_S:
                rate = None
            else:
                rate = len(self.arrivals) / RATE_WINDOW_S
            out = (rate, self.missing, self.restarts, self.bad)
            self.missing = self.restarts = self.bad = 0
            return out


def clean_name(name):
    """Lowercase, and only letters, digits and '-', so '_' still splits filenames."""
    return re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")


def save(activity, rows, missing, subject, sim):
    if not rows:
        say(f"{activity}: no samples received, nothing saved")
        return
    t0, t1 = rows[0]["t"], rows[-1]["t"]
    kept = [r for r in rows if t0 + TRIM_MS <= r["t"] <= t1 - TRIM_MS]
    if not kept:
        say(f"{activity}: only {(t1 - t0) / 1000:.1f} s, need more than "
            f"{2 * TRIM_MS / 1000:.0f} s after trimming, nothing saved")
        return

    out_dir = SIM_DIR if sim else RAW_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{subject}_{activity}_{stamp}{'_sim' if sim else ''}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS + ["label", "subject"])
        w.writeheader()
        for r in kept:
            w.writerow({**r, "label": activity, "subject": subject})

    secs = (kept[-1]["t"] - kept[0]["t"]) / 1000
    msg = f"saved {path.relative_to(REPO)}: {len(kept)} samples, {secs:.1f} s after trimming"
    if missing:
        msg += f", WARNING {missing} samples missing"
    say(msg)


def say(msg):
    """Print a line above the status line."""
    print("\r" + msg.ljust(78), flush=True)


def read_keys(out):
    """Push single keypresses (or typed lines if stdin isn't a terminal) to out."""
    if not sys.stdin.isatty():
        for line in sys.stdin:
            for ch in line.rstrip("\n"):
                out.put(ch)
        return
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], 0.1)
        if ready:
            out.put(sys.stdin.read(1))


def make_client():
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:  # paho-mqtt < 2.0
        return mqtt.Client()


def main():
    ap = argparse.ArgumentParser(description="Record labeled IMU data from MQTT to CSV.")
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--topic", default=TOPIC)
    ap.add_argument("--sim", action="store_true",
                    help="data comes from simulator.py: save to data/sim/ with '_sim' in the name")
    args = ap.parse_args()

    if args.sim:
        print("SIM MODE: saving to data/sim/ (never used for training)")
    subject = ""
    while not subject:
        subject = clean_name(input("Subject name: "))
    print(f"Recording subject '{subject}' to {(SIM_DIR if args.sim else RAW_DIR).relative_to(REPO)}/")

    rec = Recorder()
    client = make_client()
    client.on_message = rec.on_message
    client.on_connect = lambda c, *a: c.subscribe(args.topic)  # resubscribe after reconnects
    client.connect(args.broker, args.port)
    client.loop_start()

    keys = queue.Queue()
    is_tty = sys.stdin.isatty()
    old_term = termios.tcgetattr(sys.stdin) if is_tty else None
    if is_tty:
        tty.setcbreak(sys.stdin.fileno())
    threading.Thread(target=read_keys, args=(keys,), daemon=True).start()

    print("Keys: 0 standing  1 walking  2 running  3 biking  4 air-biking  space stop  q quit")

    next_report = time.monotonic() + 1.0
    try:
        while True:
            while not keys.empty():
                ch = keys.get().lower()
                if ch in LABELS or ch in (" ", "q"):
                    if rec.activity:
                        save(*rec.stop(), subject, args.sim)
                    if ch == "q":
                        return
                    if ch in LABELS:
                        rec.start(LABELS[ch])
                        say(f"recording {LABELS[ch]}")

            if time.monotonic() >= next_report:
                next_report += 1.0
                rate, missing, restarts, bad = rec.report()
                if missing:
                    say(f"WARNING: {missing} samples missing (gaps in t)")
                if restarts:
                    say("WARNING: t went backwards, did the Uno Q restart?")
                if bad:
                    say(f"WARNING: {bad} malformed messages ignored")
                if rec.first_arrival is None:
                    rate_txt = f"waiting for data on {args.topic}"
                elif rate is None:
                    rate_txt = "measuring rate..."
                else:
                    rate_txt = f"{rate:4.1f} Hz"
                    if rate < MIN_RATE_HZ:
                        rate_txt += f"  LOW RATE (<{MIN_RATE_HZ} Hz)"
                if rec.activity:
                    secs = time.monotonic() - rec.rec_started
                    status = f"REC {rec.activity} {secs:5.1f} s  {len(rec.rows)} samples  {rate_txt}"
                else:
                    status = f"idle  {rate_txt}"
                print("\r" + status.ljust(78), end="", flush=True)

            time.sleep(0.05)
    except KeyboardInterrupt:
        if rec.activity:
            save(*rec.stop(), subject, args.sim)
    finally:
        if is_tty:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term)
        client.loop_stop()
        client.disconnect()
        print("\nstopped")


if __name__ == "__main__":
    main()
