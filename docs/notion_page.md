# Wearable Gait Classifier

An IMU strapped to the thigh tells an Arduino Uno Q whether I'm **standing, walking,
running or biking**. It classifies live, every half second, with two models side by
side, and shows the result on the board's LED matrix and on a laptop dashboard.

**Demo video:** _[embed video here]_

**GitHub:** https://github.com/clabar01/me193-gait

![Live dashboard](https://raw.githubusercontent.com/clabar01/me193-gait/main/figures/dashboard.png)

---

## What it does

- Recognises four activities: standing, walking, running and biking. Biking also
  counts when done as "air-biking" lying on your back.
- Runs two classifiers at the same time on the board, so you can watch them agree
  or disagree:
  - **Model 1** uses only the peak acceleration on one axis.
  - **Model 2** uses everything the IMU measures, accelerometer and gyroscope.
- Measures cadence from the thigh's swing, in steps/min when walking or running and
  RPM when biking.
- Shows the result three ways:
  - an icon on the Uno Q's LED matrix;
  - a live web dashboard with a 3D avatar of me that copies the activity, shows the
    cadence, and lets you rotate it;
  - both models' labels side by side on the dashboard.

![The 3D avatar's five poses](https://raw.githubusercontent.com/clabar01/me193-gait/main/figures/avatar_poses.png)

## Hardware

| Part | Role |
| --- | --- |
| MPU-6050 IMU (accelerometer + gyroscope) | Strapped to the front of the mid-thigh, sampled at 50 Hz |
| Arduino Uno Q | The microcontroller reads the IMU. The Linux side runs the classifiers in Python. |
| Power bank + fanny pack | Make it wearable and wireless |
| Laptop | Web dashboard (over MQTT, `broker.hivemq.com`) |

_[photo of the device being worn]_

## How it works

1. **Sense.** The microcontroller reads the IMU 50 times a second and passes each
   sample to the Linux side over the Uno Q's internal bridge.
2. **Window.** Every 0.5 s, the last 2 s of data (100 samples) is taken as one
   window.
3. **Clean.** Single-sample glitches from the I2C bus are removed.
4. **Features.** The window is summarised into numbers: peaks, variability, rotation
   energy, cadence (an FFT of the thigh's swing) and the direction of gravity, which
   says how upright the thigh is. Training and live classification run the same
   feature code, so the models see identical inputs.
5. **Classify.** Both models run on the features. Model 2's answer is smoothed by a
   majority vote over its last three predictions.
6. **Show.** Model 2's label goes to the LED matrix. Both labels and the cadence are
   published over MQTT to the dashboard.

## The models

![How each model decides](https://raw.githubusercontent.com/clabar01/me193-gait/main/figures/model_diagram.png)

**Model 1: peak acceleration thresholds.** For each 2 s window it takes a single
number, the largest acceleration on one axis. Training picks the axis; the current
model uses the axis along the thigh. Three thresholds cut that range into the four
activities. It only looks at how hard the biggest jolt was.

**Model 2: shallow decision tree.** It may use any feature from both sensors. The
tree is kept shallow, so every decision can be read as a plain question:
1. How upright is the thigh? A thigh well off vertical means biking.
2. How big is the biggest jolt? Small means standing.
3. How much does the acceleration vary? Moderate is walking, large is running.

Features that depend on this particular sensor's calibration, like absolute
acceleration levels and axis averages, were left out on purpose. The tree only
splits on physical quantities.

Neither model is a neural network. Both are exported as plain code that runs on the
board.

## Data and evaluation

- 50 Hz sampling, 2 s windows with a 1 s step for training.
- Labeled recordings of each activity, made with a logger that counts down, beeps,
  and flags recordings with too much stillness or sensor saturation.
- Evaluation is leave-one-subject-out once several people are recorded. Until then,
  each recording is split in time (first 70% train, last 30% test).
- Both models are tested on exactly the same held-out windows.

## Results

_[to be written: accuracy and confusion matrices for each model, e.g.
`figures/model_comparison.png`]_

## Reflection

_[to be written]_

## Try it yourself

1. Strap the sensor to the front of your thigh and put the fanny pack on.
2. Open the dashboard and type your name. It stays on the screen and is never sent
   anywhere.
3. Pick your true activity in **Test mode**, then stand, walk, run or bike. Each
   model's running accuracy appears on its card.
4. Drag the 3D avatar to look at it from any side. **Reset view** brings it back.
