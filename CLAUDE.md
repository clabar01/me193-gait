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
  `wip/direct-register-driver`: its register code works, but the build goes
  silent at boot unless setup() waits a long time first (40 s worked, 2 s did
  not). Root cause not found yet. Don't merge it until it has streamed on the board.
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
