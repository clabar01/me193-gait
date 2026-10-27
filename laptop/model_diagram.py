"""Draw both models as one graphic (for the README and the Notion page).

Reads the exported models, so rerun it after retraining:
    python laptop/model_diagram.py      # -> figures/model_diagram.png

Shows how each model decides, not how well it does: no accuracies here
(those are in model1_*.png / model2_*.png / model_comparison.png).
"""

import ast
import json

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from plotting import CLASS_COLORS, GRID, MUTED, TEXT
from shared import REPO

MODEL1 = REPO / "models" / "model1.json"
MODEL2 = REPO / "models" / "model2_rules.py"
OUT = REPO / "figures" / "model_diagram.png"

# plain-language meaning of features that can appear in the tree (what a
# larger value means, so "feature <= threshold" reads naturally)
MEANING = {
    "grav_x": "how upright the thigh is (1 = vertical)",
    "grav_y": "sideways tilt of the thigh",
    "grav_z": "forward tilt of the thigh (1 = horizontal)",
    "peak_ax": "biggest jolt along the thigh",
    "peak_ay": "biggest sideways jolt",
    "peak_az": "biggest front-back jolt",
    "std_ax": "how much accel along the thigh varies",
    "std_ay": "how much sideways accel varies",
    "std_az": "how much front-back accel varies",
    "std_gx": "thigh twist variability",
    "std_gy": "thigh swing variability",
    "std_gz": "sideways swing variability",
    "amag_std": "how much |accel| varies",
    "gmag_mean": "average rotation speed",
    "gmag_max": "fastest rotation",
    "gyro_energy": "how much the thigh rotates",
    "cadence_hz": "stride frequency",
    "cadence_strength": "how rhythmic the swing is",
}
PIPELINE = ["MPU-6050 on thigh\n50 Hz accel + gyro", "2 s window\nevery 0.5 s live", "despike",
            "features\n(shared code)", "Model 1 + Model 2\n(vote of 3)", "LED matrix\n+ MQTT dashboard"]


def read_tree(path):
    """Model 2's if/else as nested dicts: {feature, threshold, yes, no} or a label string."""
    module = ast.parse(path.read_text())
    predict = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "predict")

    def node(stmts):
        stmt = next(s for s in stmts if not isinstance(s, ast.Expr))   # skip the docstring
        if isinstance(stmt, ast.Return):
            return stmt.value.value
        test = stmt.test                                  # f['feature'] <= threshold
        return {"feature": test.left.slice.value, "threshold": test.comparators[0].value,
                "yes": node(stmt.body), "no": node(stmt.orelse)}

    return node(predict.body)


def layout(tree):
    """Place each node: x by leaf order (parents centred over children), depth down.
    Returns [(node, x, depth, (parent_x, parent_depth) or None, "yes"/"no"/None)]."""
    placed, next_leaf = [], [0]

    def x_of(n):
        if isinstance(n, str):
            next_leaf[0] += 1
            return next_leaf[0] - 1
        n["x"] = (x_of(n["yes"]) + x_of(n["no"])) / 2
        return n["x"]

    def walk(n, depth, parent, branch):
        x = n["x"] if isinstance(n, dict) else leaf_x.pop(0)
        placed.append((n, x, depth, parent, branch))
        if isinstance(n, dict):
            walk(n["yes"], depth + 1, (x, depth), "yes")
            walk(n["no"], depth + 1, (x, depth), "no")

    x_of(tree)
    leaf_x = list(range(next_leaf[0]))                    # leaves are met in the same order
    walk(tree, 0, None, None)
    return placed, next_leaf[0]


def box(ax, x, y, w, h, text, face, edge, color=TEXT, size=10, weight="normal"):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                facecolor=face, edgecolor=edge, linewidth=1.2))
    ax.text(x, y, text, ha="center", va="center", fontsize=size, color=color, weight=weight)


def draw_pipeline(ax):
    ax.set_xlim(0, len(PIPELINE))
    ax.set_ylim(0, 1)
    ax.axis("off")
    for i, label in enumerate(PIPELINE):
        box(ax, i + 0.5, 0.5, 0.82, 0.62, label, "#f4f3f0", GRID, size=9.5)
        if i:
            ax.annotate("", (i + 0.09, 0.5), (i - 0.09, 0.5), arrowprops=dict(arrowstyle="->", color=MUTED))


def draw_model1(ax, model):
    thr, classes = model["thresholds"], model["classes"]
    hi = max(thr) * 1.35
    edges = [0, *thr, hi]
    for c, a, b in zip(classes, edges, edges[1:]):
        ax.barh(0, b - a, left=a, height=0.5, color=CLASS_COLORS[c], edgecolor="white", linewidth=2)
        ax.text((a + b) / 2, 0, c, ha="center", va="center", color="white", fontsize=11, weight="bold")
    for t in thr:
        ax.text(t, -0.42, f"{t:.2f} g", ha="center", va="top", fontsize=10, color=TEXT)
    ax.set_xlim(0, hi)
    ax.set_ylim(-0.9, 0.6)
    ax.axis("off")
    ax.set_title(f"Model 1: thresholds on {model['feature']} only\n"
                 "the largest acceleration along the thigh in each 2 s window",
                 loc="left", fontsize=12, color=TEXT)


def draw_model2(ax, tree):
    placed, n_leaves = layout(tree)
    depth = max(d for _, _, d, _, _ in placed)
    for n, x, d, parent, branch in placed:
        y = -d
        if parent:
            px, pd = parent
            ax.plot([px, x], [-pd - 0.28, y + 0.28], color=MUTED, linewidth=1.2, zorder=0)
            ax.text((px + x) / 2 + (-0.12 if branch == "yes" else 0.12), (-pd + y) / 2, branch,
                    ha="center", va="center", fontsize=9, color=MUTED,
                    bbox=dict(facecolor="white", edgecolor="none", pad=1))
        if isinstance(n, str):
            box(ax, x, y, 0.8, 0.42, n, CLASS_COLORS[n], CLASS_COLORS[n], color="white", size=11, weight="bold")
        else:
            text = f"{n['feature']} ≤ {n['threshold']:.3g}"
            if n["feature"] in MEANING:
                text += f"\n{MEANING[n['feature']]}"
            box(ax, x, y, 1.25, 0.56, text, "white", GRID, size=9.5)
    ax.set_xlim(-0.7, n_leaves - 0.3)
    ax.set_ylim(-depth - 0.5, 0.5)
    ax.axis("off")
    ax.set_title("Model 2: shallow decision tree on all IMU features", loc="left", fontsize=12, color=TEXT)


def main():
    model1 = json.loads(MODEL1.read_text())
    tree = read_tree(MODEL2)
    fig = plt.figure(figsize=(13, 8.5))
    grid = fig.add_gridspec(3, 1, height_ratios=[0.8, 1.0, 3.6], hspace=0.35, left=0.02, right=0.98)
    draw_pipeline(fig.add_subplot(grid[0]))
    draw_model1(fig.add_subplot(grid[1]), model1)
    draw_model2(fig.add_subplot(grid[2]), tree)
    fig.suptitle("ME193 gait classifier: how each model decides", x=0.02, ha="left", fontsize=14, color=TEXT)
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
