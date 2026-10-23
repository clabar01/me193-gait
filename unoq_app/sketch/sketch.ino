// Phase 1: read the MPU-6050 at 50 Hz and print CSV to the App Lab monitor.
//
// Sensor: MPU-6050 at 0x68 on Wire (labeled SDA/SCL header pins), 100 kHz.
// Output (Monitor, not Serial):  t,ax,ay,az,gx,gy,gz
//   t   integer ms since start, steps of exactly 20 ms; a skipped sample
//       shows up as a gap in t
//   a*  g, body frame (see AXIS REMAP below)
//   g*  deg/s, body frame, bias-corrected
// Lines starting with '#' are status messages, not data. A "# ok" or "# DOWN"
// heartbeat is printed every 5 s, so silence always means the MCU is stuck.
//
// The MPU-6050 is driven with direct register access over Wire instead of the
// Adafruit library: Adafruit_MPU6050::reset() polls a register with no timeout
// and hung the sketch when the bus failed mid-init. Every Wire call here is
// bounded by the Zephyr STM32 I2C driver's 500 ms transfer timeout, and every
// wait is a fixed delay, so a flaky connection reports an error and recovers.
//
// Libraries: Arduino_RouterBridge (bundled with the platform).

#include <Arduino_RouterBridge.h>
#include <Wire.h>

const uint8_t MPU_ADDR = 0x68;
const uint32_t I2C_HZ = 100000;
const uint32_t SAMPLE_MS = 20;                 // 50 Hz
const uint32_t SAMPLE_US = SAMPLE_MS * 1000;
const uint8_t READ_TRIES = 3;
const uint32_t REINIT_PERIOD_MS = 500;         // how often to retry while the sensor is down
const uint32_t HEARTBEAT_MS = 5000;

// Wire is I2C2 on PB11 (SDA) / PB10 (SCL), which are also Arduino pins D20/D21
// (variant overlay). Used only to check and recover the bus, then handed back
// to I2C with Wire.begin().
const uint8_t SDA_PIN = 20;
const uint8_t SCL_PIN = 21;

// MPU-6050 registers and settings
const uint8_t REG_SMPLRT_DIV = 0x19;
const uint8_t REG_CONFIG = 0x1A;
const uint8_t REG_GYRO_CONFIG = 0x1B;
const uint8_t REG_ACCEL_CONFIG = 0x1C;
const uint8_t REG_ACCEL_XOUT_H = 0x3B;         // 14 bytes: accel XYZ, temp, gyro XYZ
const uint8_t REG_PWR_MGMT_1 = 0x6B;
const uint8_t REG_WHO_AM_I = 0x75;
const uint8_t DLPF_21HZ = 0x04;                // accel 21 Hz, gyro 20 Hz
const uint8_t GYRO_1000DPS = 0x10;
const uint8_t ACCEL_8G = 0x10;
const float ACCEL_LSB_PER_G = 4096.0f;         // at +/-8 g
const float GYRO_LSB_PER_DPS = 32.8f;          // at +/-1000 deg/s

// Gyro zero-rate bias of THIS board's MPU-6050, deg/s, in SENSOR axes (X, Y, Z
// as printed on the board, before the remap). Measured at rest over 10 s on
// 2026-10-23; the monitor showed body gx 1.46, gy -1.11, gz -0.07 under the
// remap in use then (x=+sY, y=-sX, z=+sZ), i.e. sensor X 1.11, Y 1.46, Z -0.07.
// Being in sensor axes, these stay valid when the remap changes. Re-measure if the
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

bool sensorOk = false;
uint32_t lastReinitMs = 0;
uint32_t lastHeartbeatMs = 0;
uint32_t sampleCount = 0;
uint32_t errorCount = 0;     // failed reads (after all retries)
uint32_t reinitCount = 0;
uint32_t recoverCount = 0;   // bus recoveries (SDA was held low)

uint32_t nextUs;             // when the next sample is due
uint32_t tick = 0;           // sample slot number; t = tick * SAMPLE_MS

void status(const char *msg) {
  char line[128];
  snprintf(line, sizeof(line), "# %s (samples=%lu, errors=%lu, reinits=%lu, recoveries=%lu)",
           msg, (unsigned long)sampleCount, (unsigned long)errorCount,
           (unsigned long)reinitCount, (unsigned long)recoverCount);
  Monitor.println(line);
}

bool writeReg(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readRegs(uint8_t reg, uint8_t *buf, uint8_t n) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom(MPU_ADDR, n) != n) {
    return false;
  }
  for (uint8_t i = 0; i < n; i++) {
    buf[i] = Wire.read();
  }
  return true;
}

// Check that both bus lines are released (high) by reading them as plain
// inputs. If a device is holding SDA low (e.g. the MPU-6050 was cut off
// mid-byte), clock SCL up to 9 times until it lets go, then send a STOP.
// Lines are only ever pulled low or released, never driven high, so this can't
// fight the sensor. Wire.begin() hands the pins back to I2C afterwards.
bool checkAndRecoverBus() {
  pinMode(SDA_PIN, INPUT);
  pinMode(SCL_PIN, INPUT);
  delayMicroseconds(10);
  bool idle = digitalRead(SDA_PIN) == HIGH && digitalRead(SCL_PIN) == HIGH;

  if (!idle && digitalRead(SCL_PIN) == HIGH) {
    recoverCount++;
    for (uint8_t i = 0; i < 9 && digitalRead(SDA_PIN) == LOW; i++) {
      pinMode(SCL_PIN, OUTPUT);
      digitalWrite(SCL_PIN, LOW);
      delayMicroseconds(5);
      pinMode(SCL_PIN, INPUT);
      delayMicroseconds(5);
    }
    // STOP: SDA low -> high while SCL is high
    pinMode(SDA_PIN, OUTPUT);
    digitalWrite(SDA_PIN, LOW);
    delayMicroseconds(5);
    pinMode(SDA_PIN, INPUT);
    delayMicroseconds(5);
    idle = digitalRead(SDA_PIN) == HIGH && digitalRead(SCL_PIN) == HIGH;
  }

  Wire.begin();              // re-applies the I2C pin mux
  Wire.setClock(I2C_HZ);
  return idle;
}

bool initSensor() {
  if (!checkAndRecoverBus()) {
    status("bus not idle (SDA or SCL held low): check the IMU wiring");
    return false;
  }

  uint8_t who = 0;
  if (!readRegs(REG_WHO_AM_I, &who, 1)) {
    status("MPU-6050 not answering at 0x68");
    return false;
  }
  if (who != 0x68) {
    char msg[48];
    snprintf(msg, sizeof(msg), "unexpected WHO_AM_I 0x%02X", who);
    status(msg);
    return false;
  }

  if (!writeReg(REG_PWR_MGMT_1, 0x80)) {       // device reset
    return false;
  }
  delay(100);                                  // fixed wait, no polling loop
  bool ok = writeReg(REG_PWR_MGMT_1, 0x01)     // wake, PLL with gyro X clock
            && writeReg(REG_SMPLRT_DIV, 0)
            && writeReg(REG_CONFIG, DLPF_21HZ)
            && writeReg(REG_GYRO_CONFIG, GYRO_1000DPS)
            && writeReg(REG_ACCEL_CONFIG, ACCEL_8G);
  if (!ok) {
    return false;
  }

  uint8_t cfg[2];
  return readRegs(REG_GYRO_CONFIG, cfg, 2) && cfg[0] == GYRO_1000DPS && cfg[1] == ACCEL_8G;
}

// One read in sensor axes. Rejects I2C errors and stuck-bus data (all three
// axes identical, e.g. every byte 0x00 or 0xFF).
bool readOnce(float acc[3], float gyr[3]) {
  uint8_t b[14];
  if (!readRegs(REG_ACCEL_XOUT_H, b, sizeof(b))) {
    return false;
  }
  int16_t raw[7];
  for (int i = 0; i < 7; i++) {
    raw[i] = (int16_t)((b[2 * i] << 8) | b[2 * i + 1]);
  }
  // raw[0..2] accel XYZ, raw[3] temperature, raw[4..6] gyro XYZ
  if (raw[0] == raw[1] && raw[1] == raw[2] && raw[4] == raw[5] && raw[5] == raw[6]) {
    return false;
  }
  for (int i = 0; i < 3; i++) {
    acc[i] = raw[i] / ACCEL_LSB_PER_G;
    gyr[i] = raw[4 + i] / GYRO_LSB_PER_DPS - GYRO_BIAS_DPS[i];
  }
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

void setup() {
  Bridge.begin();
  Monitor.begin();

  sensorOk = initSensor();
  lastReinitMs = millis();
  lastHeartbeatMs = millis();
  status(sensorOk ? "MPU-6050 ready" : "MPU-6050 init failed, will keep retrying");
  Monitor.println("t,ax,ay,az,gx,gy,gz");

  nextUs = micros();
}

void loop() {
  if (millis() - lastHeartbeatMs >= HEARTBEAT_MS) {
    lastHeartbeatMs += HEARTBEAT_MS;
    status(sensorOk ? "ok" : "DOWN");
  }

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
      sampleCount++;
      return;
    }
  }

  errorCount++;
  sensorOk = false;
  lastReinitMs = millis() - REINIT_PERIOD_MS;   // re-init on the next slot
  status("read failed, re-initializing");
}
