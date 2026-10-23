// Phase 1: read the MPU-6050 at 50 Hz and print CSV to the App Lab monitor.
//
// Sensor: MPU-6050 at 0x68 on Wire (labeled SDA/SCL header pins), 100 kHz.
// Output (Monitor, not Serial):  t,ax,ay,az,gx,gy,gz
//   t   integer ms since start, steps of exactly 20 ms; a skipped sample
//       shows up as a gap in t
//   a*  g, body frame (see AXIS REMAP below)
//   g*  deg/s, body frame
// Lines starting with '#' are status messages, not data.
//
// Libraries: Arduino_RouterBridge, Adafruit MPU6050 (+ Adafruit Unified
// Sensor and Adafruit BusIO, which it depends on).

#include <Arduino_RouterBridge.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

const uint8_t MPU_ADDR = 0x68;
const uint32_t I2C_HZ = 100000;
const uint32_t SAMPLE_MS = 20;                 // 50 Hz
const uint32_t SAMPLE_US = SAMPLE_MS * 1000;
const uint8_t READ_TRIES = 3;
const uint32_t REINIT_PERIOD_MS = 500;         // how often to retry while the sensor is down

// Gyro zero-rate bias of THIS board's MPU-6050, deg/s, in SENSOR axes (X, Y, Z
// as printed on the board, before the remap). Measured at rest over 10 s on
// 2026-10-23; the monitor showed body gx 1.46, gy -1.11, gz -0.07, which the
// default remap maps back to sensor X 1.11, Y 1.46, Z -0.07. Re-measure if the
// sensor board is swapped. No startup calibration on purpose: the wearer may be
// moving when it boots.
const float GYRO_BIAS_DPS[3] = {1.11f, 1.46f, -0.07f};

// ===================== AXIS REMAP: edit after the mounting check =====================
// Body frame (CLAUDE.md), right-handed:
//   x along the thigh toward the hip   (+1 g standing)
//   y lateral, pointing to your right
//   z out of the front of the thigh    (+1 g sitting, thigh horizontal)
// body[i] = BODY_SIGN[i] * sensor[BODY_FROM[i]], sensor axes 0=X 1=Y 2=Z as
// printed on the board. The same remap is applied to accel and gyro.
//
// Current mounting (axis check 2026-10-23): board flat on the front of the
// thigh, chip side facing out, with the board's +X arrow pointing DOWN toward
// the knee. Then
//   body x = -sensor X,  body y = -sensor Y,  body z = +sensor Z.
// Expected with this remap: standing ax ~ +1, sitting az ~ +1, and gy goes
// POSITIVE while sitting down (the thigh rotates about +y, to your right).
// Keep the frame right-handed: if you flip one sign, also flip another or
// swap two axes, otherwise the gyro signs won't match the accel.
const uint8_t BODY_FROM[3] = {0, 1, 2};
const int8_t  BODY_SIGN[3] = {-1, -1, +1};
// =====================================================================================

Adafruit_MPU6050 mpu;
bool sensorOk = false;
uint32_t lastReinitMs = 0;
uint32_t errorCount = 0;     // failed reads (after all retries)
uint32_t reinitCount = 0;

uint32_t nextUs;             // when the next sample is due
uint32_t tick = 0;           // sample slot number; t = tick * SAMPLE_MS

bool initSensor() {
  Wire.begin();
  if (!mpu.begin(MPU_ADDR, &Wire)) {
    return false;
  }
  Wire.setClock(I2C_HZ);     // after begin(), which may reset the bus clock
  mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
  mpu.setGyroRange(MPU6050_RANGE_1000_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  return true;
}

// One read in sensor axes. getEvent() doesn't report I2C errors, so also check
// that the sensor still ACKs and that the data isn't a stuck-bus pattern (all
// three axes identical, e.g. every byte 0x00 or 0xFF).
bool readOnce(float acc[3], float gyr[3]) {
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  Wire.beginTransmission(MPU_ADDR);
  if (Wire.endTransmission() != 0) {
    return false;
  }
  if (a.acceleration.x == a.acceleration.y && a.acceleration.y == a.acceleration.z &&
      g.gyro.x == g.gyro.y && g.gyro.y == g.gyro.z) {
    return false;
  }

  acc[0] = a.acceleration.x / SENSORS_GRAVITY_STANDARD;   // m/s^2 -> g
  acc[1] = a.acceleration.y / SENSORS_GRAVITY_STANDARD;
  acc[2] = a.acceleration.z / SENSORS_GRAVITY_STANDARD;
  gyr[0] = g.gyro.x * RAD_TO_DEG - GYRO_BIAS_DPS[0];       // rad/s -> deg/s, minus bias
  gyr[1] = g.gyro.y * RAD_TO_DEG - GYRO_BIAS_DPS[1];
  gyr[2] = g.gyro.z * RAD_TO_DEG - GYRO_BIAS_DPS[2];
  return true;
}

void toBody(const float s[3], float b[3]) {
  for (int i = 0; i < 3; i++) {
    b[i] = BODY_SIGN[i] * s[BODY_FROM[i]];
  }
}

// printf's %f isn't reliably supported on this core, so format fixed-point by hand.
int appendFixed(char *buf, size_t size, float v, int decimals) {
  long scale = 1;
  for (int i = 0; i < decimals; i++) {
    scale *= 10;
  }
  long q = lroundf(v * scale);
  const char *sign = q < 0 ? "-" : "";
  q = labs(q);
  return snprintf(buf, size, ",%s%ld.%0*ld", sign, q / scale, decimals, q % scale);
}

void printSample(uint32_t t, const float acc[3], const float gyr[3]) {
  char line[96];
  int len = snprintf(line, sizeof(line), "%lu", (unsigned long)t);
  for (int i = 0; i < 3; i++) {
    len += appendFixed(line + len, sizeof(line) - len, acc[i], 4);
  }
  for (int i = 0; i < 3; i++) {
    len += appendFixed(line + len, sizeof(line) - len, gyr[i], 2);
  }
  Monitor.println(line);
}

void status(const char *msg) {
  char line[96];
  snprintf(line, sizeof(line), "# %s (errors=%lu, reinits=%lu)", msg,
           (unsigned long)errorCount, (unsigned long)reinitCount);
  Monitor.println(line);
}

void setup() {
  Bridge.begin();
  Monitor.begin();

  sensorOk = initSensor();
  lastReinitMs = millis();
  status(sensorOk ? "MPU-6050 ready" : "MPU-6050 not found, will keep retrying");
  Monitor.println("t,ax,ay,az,gx,gy,gz");

  nextUs = micros();
}

void loop() {
  // Fixed-rate scheduler on micros(): no delay(), and no drift because the
  // next deadline is always the previous one + 20 ms. I2C reads can't run
  // inside a timer interrupt, so the deadline is polled here.
  uint32_t now = micros();
  if ((int32_t)(now - nextUs) < 0) {
    return;
  }
  // Fell behind by whole periods (e.g. during a re-init): skip those slots so
  // the gap is visible in t instead of bursting out late samples.
  while ((int32_t)(now - nextUs) >= (int32_t)SAMPLE_US) {
    nextUs += SAMPLE_US;
    tick++;
  }
  uint32_t t = tick * SAMPLE_MS;
  nextUs += SAMPLE_US;
  tick++;

  if (!sensorOk) {
    if (millis() - lastReinitMs >= REINIT_PERIOD_MS) {
      lastReinitMs = millis();
      reinitCount++;
      sensorOk = initSensor();
      status(sensorOk ? "re-init OK" : "re-init failed");
    }
    return;
  }

  float sAcc[3], sGyr[3];
  for (uint8_t i = 0; i < READ_TRIES; i++) {
    if (readOnce(sAcc, sGyr)) {
      float acc[3], gyr[3];
      toBody(sAcc, acc);
      toBody(sGyr, gyr);
      printSample(t, acc, gyr);
      return;
    }
  }

  errorCount++;
  sensorOk = false;
  lastReinitMs = millis() - REINIT_PERIOD_MS;   // re-init on the next slot
  status("read failed, re-initializing");
}
