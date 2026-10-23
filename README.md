# me193-gait

A wearable activity classifier for ME193. An IMU on the thigh feeds an Arduino Uno Q,
which classifies **standing, walking, running and biking** live while worn. The result
shows on the Uno Q's LED matrix and is published over MQTT to a laptop dashboard.

The project compares two classifiers that run side by side:

- **Model 1** uses only the peak acceleration on a single axis (threshold rules).
- **Model 2** uses all IMU outputs, accelerometer and gyroscope (a shallow decision
  tree on windowed features).

Neither model uses a neural network.

## Hardware setup

| Part | Notes |
| --- | --- |
| Arduino Uno Q | The Linux side runs Python. The microcontroller side runs an Arduino sketch. They communicate through Arduino_RouterBridge. |
| MPU-6050 IMU (accel + gyro) | Powered from 3.3V. Connected over I2C (address 0x68) with about 45 cm of twisted wire. Strapped to the front of the mid-thigh. |
| Power bank | Powers the Uno Q. |
| Fanny pack | Holds the Uno Q and power bank on the hip. |

Data flow:

```
IMU --I2C--> Uno Q MCU (sketch) --RouterBridge--> Uno Q Linux (Python)
                                                     |-> LED matrix icon
                                                     '-> MQTT --> laptop dashboard
```

## Method

- Sampling rate: 50 Hz
- Windows: 2 s long, with a 1 s step
- Data: at least 3 people
- Evaluation: leave-one-subject-out
- Biking can be recorded on a bike or as air-biking while lying on your back

## MQTT

| Setting | Value |
| --- | --- |
| Broker | `broker.hivemq.com` |
| Port | `1883` |
| Topic prefix | `ME193/ceci/gait/` |

This is a public broker, so anyone can read or publish on these topics.

## Folder structure

```
me193-gait/
├── unoq_app/        Uno Q app (Arduino App Lab layout)
│   ├── sketch/      microcontroller sketch: reads the IMU, sends samples over the bridge
│   └── python/      Linux-side Python: windowing, both classifiers, LED matrix, MQTT
├── tools/           i2c_scanner/: standalone sketch for checking the IMU wiring
├── laptop/          data logger, model training and web dashboard scripts
├── data/
│   ├── raw/         labeled CSV recordings from the real sensor (the only data used for training)
│   └── sim/         recordings of simulator data, made with logger.py --sim (never used for training)
├── models/          exported model files loaded by the Uno Q app
├── figures/         plots for the project write-up
├── requirements.txt laptop-side Python dependencies
└── CLAUDE.md        project context for Claude Code
```

## Installation (laptop)

Requires Python 3.

```bash
git clone <this-repo-url>
cd me193-gait
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

The scripts are still being written. The workflow will be:

1. **Collect data.** Run the Uno Q app in logging mode and record labeled sessions
   for each activity and person on the laptop. Recordings are saved to `data/raw/`.
2. **Train.** Run the training scripts in `laptop/` to fit both models with
   leave-one-subject-out evaluation. Exported models go in `models/` and plots go in
   `figures/`.
3. **Deploy.** Copy the exported models into the Uno Q app and run it from Arduino App Lab.
4. **Watch live.** Start the laptop dashboard. It subscribes to the MQTT topics and
   shows both models' predictions side by side.

The exact commands will be added here as each script is written.

### Deploying to the Uno Q

`unoq_app/` is the complete App Lab app. To deploy it over SSH:

```bash
scp -r unoq_app/app.yaml unoq_app/python unoq_app/sketch arduino@<board>.local:ArduinoApps/me193_gait/
ssh arduino@<board>.local arduino-app-cli app stop ~/ArduinoApps/me193_gait
ssh arduino@<board>.local arduino-app-cli app start ~/ArduinoApps/me193_gait
ssh arduino@<board>.local arduino-app-cli monitor     # watch the CSV output
```

Use `stop` then `start`: `app restart` sometimes fails with "app is running".

The first time, create the app on the board with
`arduino-app-cli app new me193_gait`, or open it in App Lab. Then make it start at
boot, so it runs without SSH or App Lab:

```bash
ssh arduino@<board>.local arduino-app-cli properties set default ~/ArduinoApps/me193_gait
```

Only one monitor connection receives the output. If the monitor shows nothing,
first check for leftover `arduino-app-cli monitor` processes on the board and kill
them. If it's still silent, power-cycle the board.

### Recording data

```bash
python laptop/logger.py
```

The logger asks for the subject's name. Then use these keys:

| Key | Action |
| --- | --- |
| `0` | record standing |
| `1` | record walking |
| `2` | record running |
| `3` | record biking |
| `4` | record air-biking |
| space | stop and save the current recording |
| `q` | quit |

Each recording is saved as `data/raw/<subject>_<activity>_<timestamp>.csv`, with the
first and last 3 s trimmed off. While it runs, the logger shows a live sample count and
warns if the rate drops below 45 Hz or samples go missing.

To plot a recording:

```bash
python laptop/plot_raw.py data/raw/<file>.csv                 # opens a window
python laptop/plot_raw.py data/raw/<file>.csv --out figures/x.png
```

### Testing without the hardware

`laptop/simulator.py` publishes **fake** IMU data in the same MQTT format as the Uno Q.
Use it only for testing. When you record its output, use `--sim` so the files go to
`data/sim/` and never mix with real data.

```bash
python laptop/simulator.py            # keys: s w r b a switch activity, q quits
python laptop/simulator.py --random --subject p2
python laptop/logger.py --sim         # in a second terminal
```

## Links

- Notion project page: _TBD_
