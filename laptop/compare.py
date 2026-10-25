"""Phase 5: Model 1 and Model 2 held-out confusion matrices side by side.

Reads models/eval_model1.csv and models/eval_model2.csv (written by model1.py
and model2.py on the same splits) and saves figures/model_comparison.png.

Usage:
    python laptop/model1.py && python laptop/model2.py && python laptop/compare.py
"""

import json

import matplotlib.pyplot as plt
import pandas as pd

import plotting
from shared import REPO, shared_features

F = shared_features()


def main():
    e1 = pd.read_csv(REPO / "models" / "eval_model1.csv", index_col="window")
    e2 = pd.read_csv(REPO / "models" / "eval_model2.csv", index_col="window")
    common = e1.index.intersection(e2.index)
    if len(common) != len(e1) or len(common) != len(e2):
        print(f"note: comparing the {len(common)} windows both models were tested on")
    e1, e2 = e1.loc[common], e2.loc[common]
    present = set(e1["label"]) | set(e1["pred"]) | set(e2["pred"])
    classes = [c for c in F.CLASSES if c in present]

    m1 = json.loads((REPO / "models" / "model1.json").read_text())
    method = m1["evaluation"]["method"]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.9))
    for ax, ev, title in ((axes[0], e1, f"Model 1: peak accel ({m1['feature']})"),
                          (axes[1], e2, "Model 2: all IMU (decision tree)")):
        acc = plotting.accuracy(ev["label"], ev["pred"])
        plotting.plot_confusion(ax, plotting.confusion(ev["label"], ev["pred"], classes), classes,
                                f"{title}\nheld-out accuracy {acc:.0%}")
        print(f"{title}: {acc:.1%} on {len(ev)} held-out windows")
    fig.suptitle(f"Held-out windows: {method}", x=0.01, ha="left", color=plotting.MUTED, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = REPO / "figures" / "model_comparison.png"
    fig.savefig(out, dpi=150)
    print(f"saved {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
