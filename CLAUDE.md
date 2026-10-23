# CLAUDE.md

Context for Claude Code sessions working in this repo.

## Project

ME193 robotics class project: a wearable gait/activity classifier. It classifies
**standing, walking, running and biking** (biking can be done as air-biking
while lying on your back) live while the device is worn.

Due **Oct 27, 2026**. It is graded by 3 peers who each test it live, and it needs
a Notion page with a demo video, a graphic of the model, and a GitHub link.

## Hardware

- **Arduino Uno Q.** The Linux side runs Python and the microcontroller side runs
  an Arduino sketch. The two sides talk through **Arduino_RouterBridge**.
- **MPU-6050 IMU** (accel + gyro) on I2C at 0x68, powered from 3.3V, wired to the
  Uno Q's labeled SDA/SCL header pins with about 45 cm of twisted wire, and strapped
  to the front of the mid-thigh.
- The sketch subtracts a **hardcoded gyro bias** (`GYRO_BIAS_DPS` in
  `unoq_app/sketch/sketch.ino`). It is specific to this MPU-6050 board, is in
  sensor axes (before the remap), and must be re-measured if the board is
  swapped. There is deliberately no startup calibration, because the wearer may
  be moving at boot.
- The board is reachable at `arduino@AirFour.local` (SSH, no password). The app is
  `~/ArduinoApps/me193_gait`, managed with `arduino-app-cli`, and is set as the
  board's default app (`properties set default`) so it starts at boot. Redeploy
  with `app stop` + `app start`; `app restart` can fail with "app is running".
- The sketch on `main` uses the **Adafruit MPU6050** library (2.2.9, plus Unified
  Sensor and BusIO). It streams fine, but `Adafruit_MPU6050::reset()` polls a
  register with no timeout, so a bus failure during init can hang the MCU (silent
  monitor; fixed by a power cycle). A direct-register replacement is on branch
  `wip/direct-register-driver`: its register code works (a traced run streamed at
  50 Hz). Its "silent at boot" runs were probably the USB monitor proxy described
  below, not the sketch. Re-test it by reading the USB port (or with USB
  unplugged) before merging.
- **After any reflash, power-cycle the board before trusting it** (the student's
  rule, 2026-10-23). Context: what looked like a "reflash hang" was most likely
  the board's `arduino-router-serial` service (`socat` from the monitor port
  127.0.0.1:7500 to `/dev/ttyGS0`). It starts whenever the board's USB port is
  connected to a computer and takes the monitor connection, so the CSV goes out
  the USB cable and an SSH `arduino-app-cli monitor` shows nothing. On the cold
  boot of 2026-10-23 19:05 the sketch streamed perfectly over USB
  (`/dev/cu.usbmodem*` on the Mac) while the SSH monitor was empty. To check a
  USB-connected board, read the Mac's USB serial port, not the SSH monitor.
- Only one `arduino-app-cli monitor` connection gets the output. A stale monitor
  (e.g. left over from a closed SSH session) silently takes it all, and
  `monitor` ignores SIGTERM. Use `timeout -k 2 N arduino-app-cli monitor` and
  kill leftover monitor processes before concluding the sketch is silent.
- `AirFour.local` sometimes doesn't resolve after a reboot; the board's IP was
  192.168.1.173 on 2026-10-23.
- The Uno Q and a power bank ride in a fanny pack on the hip.

## Models (both required, no neural nets)

- **Model 1** uses ONLY the peak acceleration on one axis. The plan is thresholds on
  peak accel.
- **Model 2** uses all IMU outputs (accel + gyro). The plan is a shallow decision
  tree on windowed features: stats, FFT cadence, gyro energy, gravity direction.

## Data and evaluation

- Sample at **50 Hz**. Use **2 s windows with a 1 s step** (100 samples, 50% overlap).
- Data from **at least 3 people**.
- Evaluate **leave-one-subject-out**, so every recording must be traceable to a
  subject and a label.

## Cadence

The IMU is on one thigh, so the thigh swing (gyro) repeats once per **stride**
(2 steps). The accel also has energy at the step rate (2x stride) from the other
foot's strike. Typical stride rates: walking ~0.9 Hz, running ~1.4 Hz, biking
~1.2 Hz, air-biking ~1.1 Hz.

Body frame and sign convention (right-handed, verified on the real sensor):
x along the thigh toward the hip (+1 g standing), z out of the front of the
thigh (+1 g sitting), y = z × x pointing to the wearer's **right**. Sitting down,
or swinging the thigh forward, is a positive rotation about y, so **gy > 0**
(about +85 deg/s peak in the sit-down check). The simulator uses the same sign:
its gy = +d(pitch)/dt, and pitch increases toward sitting.

Cadence features (e.g. the FFT peak) must use the **signed `gy` axis** (lateral,
the thigh's swing axis), **not |gyro|**. The magnitude rectifies the swing, so it
peaks twice per stride and doubles the apparent cadence.

For display, report cadence as:
- walking and running: **steps/min = 2 x stride frequency (Hz) x 60**
- biking and air-biking: **RPM = stride frequency (Hz) x 60**

## Live system

- Classification runs on the **Uno Q Python side**.
- The **LED matrix** shows an icon per activity.
- Results publish over **MQTT**: broker `broker.hivemq.com`, port `1883`, topics
  under `ME193/ceci/gait/`.
- A **laptop web dashboard** shows both models side by side.
- **Data path (Phase 2, working 2026-10-23):** sketch → `Bridge.notify("imu_sample",
  t, ax, ay, az, gx, gy, gz)` at 50 Hz → `unoq_app/python/main.py` batches 5
  samples → `ME193/ceci/gait/raw` (~10 msg/s, the format `laptop/logger.py` and
  the simulator use). The Bridge handler only appends to a batch; a separate
  thread publishes from a 30 s bounded queue, so MQTT can't slow the sensor and
  short WiFi drops don't lose data. paho reconnects by itself.
  `ME193/ceci/gait/status` (every 5 s) carries board wall time, last `t`, rate,
  queue depth and the sketch's last status line. Measured: 49.93 samples/s, no
  gaps in 55 s; board→laptop lag median ~113 ms (p90 ~183 ms), about the same as
  the laptop's own HiveMQ round trip, so the public broker dominates.
- The sketch's per-sample CSV on Monitor is off (`PRINT_CSV = false`) to keep the
  router link light; `#` status lines still print.
- Optional later: Whoop heart rate over BLE, shown on the dashboard only. It is
  **never a model input**.

## Repo layout

- `unoq_app/`: Uno Q app in App Lab style, with `sketch/` (MCU) and `python/` (Linux side)
- `laptop/`: data logger, training and dashboard scripts
- `data/raw/`: labeled CSVs from the real sensor (committed, not gitignored)
- `data/sim/`: recordings of simulator data, saved with `--sim`, with "sim" in
  the filename. **Training and evaluation scripts must only ever read `data/raw/`.**
- `models/`: exported model files
- `figures/`: plots for the Notion page

## Ground rules

- Do not write the reflection answers for the assignment, and do not claim which
  model is better or put results in the README. The student writes those from real data.
- Update existing files (README, .gitignore) instead of overwriting them.
