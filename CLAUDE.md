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
- Sensor ranges: **±16 g** and **±2000 deg/s**, 21 Hz low-pass. Raised from ±8 g /
  ±1000 deg/s on 2026-10-23 after a running recording saturated; recordings made
  before then used the old ranges (values below the old limits are in the same
  units, just coarser). `laptop/logger.py`'s range check must match the sketch.
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
- **Prediction format (defined 2026-10-23; the board must publish exactly this):**
  topic `ME193/ceci/gait/pred`, one message every 0.5 s (2 s window), JSON
  `{"t": <ms, t of the window's last sample>, "model1": <label>, "model2": <label>,
  "cadence_hz": <stride frequency, 0 when standing>}`. Labels are exactly
  `standing`, `walking`, `running`, `biking` (air-biking is reported as `biking`).
  `model2` is the majority vote of Model 2's last 3 predictions; `model1` is raw.
  `laptop/simulator.py --pred` publishes fake predictions in this format.
- **Dashboard:** `laptop/dashboard.html`, a single file, MQTT over WebSockets
  (`wss://broker.hivemq.com:8884/mqtt`, mqtt.js from jsDelivr). It only subscribes,
  never publishes; the viewer's name stays in the page (public broker). The avatar
  follows model2; upright bike vs air-bike comes from the mean `ax` over the last
  2 s of raw (below -0.3 g = lying on back). The connection light uses the status
  topic (the simulator publishes one too). `HEAD_PHOTO` in the file swaps the head
  circle for a face photo.
  "Switch player" returns to the name screen and replaces the page's `player`
  object (name, face photo); put any per-player stats in that object so they
  reset with it. The MQTT connection stays open across players (no reconnect).
  Test mode: buttons for the true activity; each prediction arriving while one is
  selected is scored right/wrong for each model, shown as accuracy on the cards.
  Counts live in `player.test` (reset on Switch player).
- **3D avatar (2026-10-26):** a `<script type="module">` at the end of
  dashboard.html loads three.js 0.170.0 (import map, jsDelivr) and
  `laptop/assets/avatar.glb` with GLTFLoader. The GLB is the student's Meshy
  character with all its clips; it is committed with its texture shrunk to
  1024 px by `laptop/shrink_glb.py` (rerun after a re-export). Clips are picked
  by name (`CLIPS`):
  - standing = `Listening_Gesture`, walking = `Walking`, running = `Running`.
  - Biking = the first 0-0.62 s of `Unicycle_Jump_Dismount`, played ping-pong.
    That span is half a pedal turn, so forward and back makes one full turn; the
    clip jumps off the unicycle after ~1 s, and that part is never played. A
    unicycle wheel is fitted under it.
  - Air-bike = `bicycle_crunch`.

  Each looping clip is one stride or pedal turn (measured), so timeScale =
  smoothed cadence_hz x cycle length. Hips x/z are pinned (in place). Each
  clip gets a floor offset: the crunch is exported 1.4 m below the floor, and
  the bike is lowered so the wheel stands on the floor. The offset is blended
  by action weight during cross-fades. Pose names are the stick figure's
  (`poseName()`); the classic script calls `avatar3d.update(...)` instead of
  `drawAvatar` when 3D is on. It falls back to the stick figure on file://,
  without three.js, or if the GLB is missing, and the reason shows in the
  panel. The page must be served: `python laptop/serve.py` (localhost:8000,
  127.0.0.1 only). Face photo: `HEAD_PHOTO` / `player.photo` becomes a round sprite placed at the head bone.
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

## Shared feature code

- **`unoq_app/python/features.py` is the one feature module** for both training
  (laptop) and live classification (board). It lives in the board app folder so it
  is deployed with the app; laptop scripts add `unoq_app/python` to `sys.path` and
  import it. Never duplicate feature code elsewhere: training and live must compute
  features identically. Phase 4 (models) builds on this module.
- **`despike()` runs first, before every feature, including Model 1's peak accel.**
  It replaces a sample with its neighbours' average when, on any axis, it is more
  than 6 g / 500 deg/s from both neighbours while the neighbours are within
  3 g / 250 deg/s of each other (a corrupted I2C read). Apply it to the continuous
  stream (whole recording, or a rolling buffer on the board), not to each 2 s
  window alone, so window-edge samples have both neighbours.
- The thresholds are deliberately high: at 3 g / 300 deg/s it also removed
  single-axis 4-5.5 g accel peaks in walking that look like real heel strikes,
  which Model 1 needs. On the 2026-10-23 data it replaces the known glitch
  (air-biking t=1630800) and one sample inside a saturated burst (t=1603660).
  Re-check it on the first running recording at +/-16 g.
- The board's Python container doesn't have numpy yet: add it to
  `unoq_app/python/requirements.txt` when features.py is first used live.
- Tests: `python laptop/test_features.py`.
- It also holds `window_starts()` (2 s windows, 1 s step, skipping gaps in t),
  `window_features()` (all Model 1 + Model 2 features, cadence from signed `gy`),
  `merge_label()` (air-biking -> biking) and `model1_predict()` (applies
  models/model1.json). Laptop scripts load it by path via `laptop/shared.py`
  (`shared_features()`), because `laptop/features.py` has the same module name.

## Phase 4/5 pipeline (rerun whenever data/raw/ changes)

```bash
python laptop/features.py   # data/raw/*.csv -> data/windows.csv
python laptop/model1.py     # -> models/model1.json, figures/model1_*.png
python laptop/model2.py     # -> models/model2_rules.py, figures/model2_*.png
python laptop/compare.py    # -> figures/model_comparison.png
```

- Evaluation (`laptop/evaluation.py`, shared by both models): leave-one-subject-out
  when there are 2+ subjects; with 1 subject, a time split inside each recording
  (first 70% train, last 30% test, boundary window dropped). Both models use the
  same splits; held-out predictions go to `models/eval_model{1,2}.csv`.
- Everything adapts to whichever classes are present.
- Model 1 picks the axis (peak_ax/ay/az) with the best held-out accuracy; classes
  are ordered by their median peak on that axis and thresholds are an exact
  accuracy-maximising search. Model 2 tries depths 2-5 (ties -> shallower),
  `min_samples_leaf=3`, and is exported as plain if/else (branches whose leaves
  all agree are collapsed); the export is checked against sklearn on every window.
- **Model 2 leaves out calibration-sensitive features** (`CALIBRATION_SENSITIVE`
  in laptop/model2.py): `amag_mean/min/max`, `mean_ax/ay/az`, `mean_gx/gy/gz`.
  With them, the root split was `amag_mean <= 0.961`, which only reflected this
  sensor reading ~0.95 g at rest and would not carry over to other people or
  sensors. Without them (2026-10-24, 1 subject, same splits) the tree is
  `gyro_energy <= 1752 -> standing` (is the thigh rotating?), then
  `grav_x <= 0.966 -> biking else walking` (is the thigh vertical?), both physical
  and calibration-robust, and held-out accuracy went from 97% to 100% (72 windows).
  Keep Model 2 on variability, cadence, peaks and gravity *direction*. Watch the
  `grav_x` split once running/upright biking exist: walking sits near 0.99.

## Phase 6: live classification on the board

- `unoq_app/python/live.py` (`LiveClassifier`): rolling buffer of the 2 s window
  plus one sample each side (so despike() sees both neighbours), every 25 samples
  (0.5 s) -> despike -> `window_features` -> Model 1 + Model 2 (vote of 3) ->
  prediction dict. Pure numpy, no Arduino imports. Windows with a gap in t are
  skipped; t going backwards resets it.
- `main.py`: the Bridge handler only calls `live.add()` (cheap); snapshots go to a
  worker thread that classifies, publishes to the pred topic and calls
  `Bridge.call("show_activity", label)` on change (and every 5 s). If numpy or the
  models fail to load, it logs `live classification OFF` and keeps forwarding raw
  data (the logger must never be blocked by Phase 6). Status messages now include
  `live` and `model2`.
- Sketch: `show_activity(String)` (Bridge provider) only records the request;
  `loop()` draws the 13x8 icon with `Arduino_LED_Matrix` (bundled with the board
  package) via `renderBitmap`. Icons are `#`/`.` text rows in the sketch
  (`ICON_STANDING/WALKING/RUNNING/BIKING`); `python laptop/run_board_app.py --icons`
  prints them.
- Models on the board load from `unoq_app/python/models/`. `laptop/model1.py` and
  `laptop/model2.py` write `models/` AND copy into that folder, so after retraining:
  `laptop/deploy_board.sh` (Python + models) or `laptop/deploy_board.sh --sketch`
  (also reflashes the sketch -> power-cycle). It refuses to deploy if the app's
  model copies are stale. `BOARD=arduino@<ip>` if the .local name fails.
- `laptop/run_board_app.py` runs the real `main.py` on the laptop with a stand-in
  `arduino.app_utils`, fed from an MQTT raw stream (default: simulator on
  `ME193/ceci/gait/test/sim/raw`), publishing under `ME193/ceci/gait/test/`
  (dashboard: `python laptop/serve.py --query "prefix=ME193/ceci/gait/test"`)
  (main.py reads `GAIT_TOPIC_PREFIX`, unset on the board). LED calls print as ASCII.
- **Board state 2026-10-26 18:28 UTC:** fully deployed with
  `laptop/deploy_board.sh --sketch` (LED sketch compiled and flashed in ~3.5 min),
  then power-cycled. Verified after the cold boot: numpy installed
  ("Requirements already installed"), `models loaded`, 50 Hz, MQTT up, preds on
  `ME193/ceci/gait/pred` every 500 ms, no `show_activity` errors. After a cold
  boot the first prediction came ~35 s after "App started".
  If a `show_activity` call fails, main.py warns every 5 s (LED_REFRESH_S), not on
  every prediction.

## Ground rules

- Do not write the reflection answers for the assignment, and do not claim which
  model is better or put results in the README. The student writes those from real data.
- Update existing files (README, .gitignore) instead of overwriting them.
