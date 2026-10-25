"""Phase 5, Model 1: thresholds on the peak acceleration of ONE axis.

For each axis (peak_ax, peak_ay, peak_az) the classes are ordered by their
median peak on that axis, and the thresholds between them are chosen to
maximise accuracy (exact search over candidate cut points). The axis with the
best held-out accuracy (see evaluation.py) is kept, refit on all windows, and
exported to models/model1.json for the board (shared_features.model1_predict).

Works with whatever classes are present in data/windows.csv.

Outputs:
    models/model1.json            the model
    models/eval_model1.csv        held-out predictions (used by compare.py)
    figures/model1_thresholds.png per-class histograms + thresholds, all 3 axes
    figures/model1_confusion.png  held-out confusion matrix

Usage:
    python laptop/model1.py
"""

import json
from datetime import date

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import plotting
from evaluation import classes_present, splits
from shared import REPO, copy_to_app, shared_features

F = shared_features()
MAX_CANDIDATES = 400


def fit_thresholds(values, labels, classes):
    """Order classes by median value; find the K-1 thresholds maximising accuracy."""
    values, labels = np.asarray(values, dtype=float), np.asarray(labels)
    order = sorted(classes, key=lambda c: np.median(values[labels == c]) if (labels == c).any() else np.inf)
    u = np.unique(values)
    cands = (u[:-1] + u[1:]) / 2 if len(u) > 1 else u.copy()
    if len(cands) > MAX_CANDIDATES:
        cands = np.unique(np.quantile(cands, np.linspace(0, 1, MAX_CANDIDATES)))
    bounds = np.concatenate([[-np.inf], cands, [np.inf]])
    # cum[k][j] = number of class-k values <= bounds[j]
    cum = [np.searchsorted(np.sort(values[labels == c]), bounds, side="right") for c in order]

    n_b = len(bounds)
    best = cum[0].astype(float).copy()            # class 0 covers (-inf, bounds[j]]
    back = []
    for k in range(1, len(order)):
        new = np.full(n_b, -np.inf)
        arg = np.zeros(n_b, dtype=int)
        for b in range(n_b):
            # class k covers (bounds[a], bounds[b]]
            score = best[:b + 1] + (cum[k][b] - cum[k][:b + 1])
            a = int(np.argmax(score))
            new[b], arg[b] = score[a], a
        back.append(arg)
        best = new
    # last class must reach +inf
    cuts, b = [], n_b - 1
    for arg in reversed(back):
        b = arg[b]
        cuts.append(bounds[b])
    thresholds = [float(c) for c in reversed(cuts)]
    return {"classes": order, "thresholds": thresholds}


def predict(values, model):
    return [F.model1_predict({"v": v}, {**model, "feature": "v"}) for v in values]


def main():
    windows = pd.read_csv(REPO / "data" / "windows.csv")
    classes = classes_present(windows, F.CLASSES)
    method, folds = splits(windows)
    print(f"{len(windows)} windows, classes: {', '.join(classes)}")
    print(f"evaluation: {method}\n")

    held_out = {}
    for feat in F.MODEL1_FEATURES:
        preds = pd.Series(index=windows.index, dtype=object)
        for _, tr, te in folds:
            m = fit_thresholds(windows.loc[tr, feat], windows.loc[tr, "label"], classes)
            preds.loc[te] = predict(windows.loc[te, feat], m)
        tested = preds.dropna().index
        held_out[feat] = (preds, plotting.accuracy(windows.loc[tested, "label"], preds.loc[tested]))
        print(f"  {feat}: held-out accuracy {held_out[feat][1]:.1%}")

    best = max(F.MODEL1_FEATURES, key=lambda f: held_out[f][1])   # ties: first in ax, ay, az
    final = fit_thresholds(windows[best], windows["label"], classes)
    model = {
        "feature": best,
        "classes": final["classes"],
        "thresholds": final["thresholds"],
        "trained_on": {"subjects": sorted(windows["subject"].unique()), "windows": int(len(windows)),
                       "classes": classes},
        "evaluation": {"method": method,
                       "held_out_accuracy": {f: round(held_out[f][1], 4) for f in F.MODEL1_FEATURES}},
        "created": date.today().isoformat(),
    }
    (REPO / "models").mkdir(exist_ok=True)
    (REPO / "models" / "model1.json").write_text(json.dumps(model, indent=2) + "\n")
    copy_to_app(REPO / "models" / "model1.json")
    print(f"\nchosen: {best}; thresholds on all data: "
          + " | ".join(f"{c} <= {t:.2f}" for c, t in zip(final["classes"], final["thresholds"]))
          + f" | else {final['classes'][-1]}")

    preds = held_out[best][0]
    tested = preds.dropna().index
    ev = windows.loc[tested, ["subject", "recording", "t_start", "label"]].assign(pred=preds.loc[tested])
    ev.to_csv(REPO / "models" / "eval_model1.csv", index_label="window")
    plot_thresholds(windows, classes, held_out, best)
    fig, ax = plt.subplots(figsize=(5.2, 4.6))
    cm = plotting.confusion(ev["label"], ev["pred"], classes)
    plotting.plot_confusion(ax, cm, classes, f"Model 1 ({best}), held out: {held_out[best][1]:.0%}")
    fig.tight_layout()
    fig.savefig(REPO / "figures" / "model1_confusion.png", dpi=150)
    print("saved models/model1.json (+ copy in unoq_app/python/models/), models/eval_model1.csv, "
          "figures/model1_thresholds.png, figures/model1_confusion.png")


def plot_thresholds(windows, classes, held_out, best):
    fig, axes = plt.subplots(1, len(F.MODEL1_FEATURES), figsize=(15, 4.4))
    for ax, feat in zip(axes, F.MODEL1_FEATURES):
        v = windows[feat]
        bins = np.linspace(0, max(v.max() * 1.05, 1.0), 40)
        for c in classes:
            ax.hist(v[windows["label"] == c], bins=bins, color=plotting.CLASS_COLORS[c], alpha=0.65,
                    label=c, edgecolor="white", linewidth=0.5)
        m = fit_thresholds(v, windows["label"], classes)
        top = ax.get_ylim()[1]
        for i, t in enumerate(m["thresholds"]):
            if np.isfinite(t):
                ax.axvline(t, color=plotting.TEXT, linestyle="--", linewidth=1.2)
                # stagger the labels so close thresholds don't overlap
                ax.text(t, top * (1 - 0.08 * i), f" {t:.2f} g", color=plotting.TEXT, fontsize=9, va="top")
        mark = "  (chosen)" if feat == best else ""
        ax.set_title(f"{feat}: held out {held_out[feat][1]:.0%}{mark}", loc="left", color=plotting.TEXT,
                     fontsize=12, fontweight="bold" if mark else "normal")
        ax.set_xlabel("peak |accel| on this axis in a 2 s window (g)", color=plotting.MUTED)
        plotting.style(ax)
    axes[0].set_ylabel("windows", color=plotting.MUTED)
    axes[0].legend(frameon=False)
    fig.suptitle("Model 1: one threshold set per axis (dashed), fit on all windows",
                 x=0.01, ha="left", color=plotting.TEXT, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(REPO / "figures" / "model1_thresholds.png", dpi=150)


if __name__ == "__main__":
    main()
