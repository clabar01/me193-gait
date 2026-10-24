"""Shared feature code for training (laptop) and live classification (board).

This module lives in unoq_app/python/ so it is deployed with the board app;
laptop scripts import it from there. Both sides must compute features with
exactly this code so the models see the same inputs in training and live.

Samples are an (N, 6) array with columns AXES, accel in g and gyro in deg/s,
body frame, 50 Hz.

Pipeline order: despike() FIRST, then any feature (including Model 1's peak
accel). Run despike() on the continuous stream (a whole recording, or a rolling
buffer on the board), not on each 2 s window by itself, so samples at window
edges still have both neighbours.
"""

import numpy as np

AXES = ("ax", "ay", "az", "gx", "gy", "gz")

# A sample is a spike if, on any axis, it is more than SPIKE from BOTH
# neighbours while the neighbours are within AGREE of each other. Tuned on the
# first real recordings (2026-10-23): the one corrupted I2C read jumped 11 g and
# 750 deg/s for a single sample on four axes. At 3 g / 300 deg/s the filter
# also removed three single-axis accel peaks (4.0-5.5 g in walking, 3.5 g in
# air-biking) whose gyro stayed smooth, which look like real heel-strike/kick
# impacts. Model 1 is peak accel, so those must survive: 6 g / 500 deg/s keeps
# them and still catches the glitch. Re-check this when running data exists.
SPIKE = np.array([6.0, 6.0, 6.0, 500.0, 500.0, 500.0])
AGREE = SPIKE / 2


def despike(samples):
    """Replace single-sample glitches with the average of their neighbours.

    samples: (N, 6) array-like in AXES order. Returns (cleaned copy, indices
    of the replaced samples). A corrupted read garbles every axis of that
    sample, so the whole sample is replaced, not just the axis that tripped
    the check. The first and last samples have only one neighbour and are
    left as they are; two bad samples in a row are not caught.
    """
    x = np.array(samples, dtype=float)
    if len(x) < 3:
        return x, np.array([], dtype=int)

    prev, cur, nxt = x[:-2], x[1:-1], x[2:]
    far = (np.abs(cur - prev) > SPIKE) & (np.abs(cur - nxt) > SPIKE)
    agree = np.abs(prev - nxt) <= AGREE
    bad = np.flatnonzero((far & agree).any(axis=1)) + 1

    # Neighbours of a bad sample are never bad themselves here (they'd need
    # their own neighbours to agree across the spike), so this is safe in one pass.
    x[bad] = (x[bad - 1] + x[bad + 1]) / 2
    return x, bad
