"""Evaluation charts (matplotlib PNGs): accuracy and tokens by config, confusion matrix.

Mock configs are left out of the bar charts on purpose: their score only shows that the pipeline
agrees with the sample generator, and a 1.00 bar would hide the real models. Output is
byte-stable for the same results (no timestamp or version in the PNG metadata). Figure margins
and tick positions are layout constants, not tunables; everything visible is in ``eval.charts``.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: before pyplot

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from vendorguard.config_models.core import ChartSettings  # noqa: E402
from vendorguard.errors import ConfigError  # noqa: E402
from vendorguard.eval.metrics import GOLD_LABELS, PRED_LABELS  # noqa: E402
from vendorguard.eval.results import ConfigRecord, EvalResults, Outcome  # noqa: E402

FILES = {
    "accuracy": "accuracy_by_config.png",
    "tokens": "tokens_by_config.png",
    "confusion": "confusion_best.png",
}
PNG_METADATA = {"Software": None}  # keeps the bytes identical between runs


def _model_configs(results: EvalResults) -> list[ConfigRecord]:
    """Configs that finished and used a real model, best accuracy first (ties by name)."""
    ok = [c for c in results.configs if c.outcome is Outcome.OK and c.aggregate and c.llm != "mock"]
    if not ok:
        raise ConfigError("no finished model config in the results: run `vg eval` first")
    return sorted(ok, key=lambda c: (-(c.aggregate.accuracy if c.aggregate else 0), c.name))


def _frame(cs: ChartSettings, rows: int, title: str) -> tuple[Figure, Axes]:
    fig, ax = plt.subplots(figsize=(cs.width_in, cs.row_height_in * rows + 0.9))
    fig.patch.set_facecolor(cs.surface)
    ax.set_facecolor(cs.surface)
    fig.suptitle(title, x=0.02, ha="left", fontsize=cs.title_size, color=cs.ink, fontweight="bold")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(cs.grid)
    ax.tick_params(colors=cs.ink_secondary, length=0)
    ax.xaxis.grid(True, color=cs.grid, linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _save(fig: Figure, path: Path, cs: ChartSettings) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=cs.dpi, facecolor=cs.surface, metadata=PNG_METADATA)
    plt.close(fig)
    return path


def accuracy_chart(results: EvalResults, cs: ChartSettings, path: Path) -> Path:
    """Horizontal bars: accuracy per config; the best one is highlighted, the rest muted."""
    configs = _model_configs(results)
    total = configs[0].aggregate.controls if configs[0].aggregate else 0
    fig, ax = _frame(cs, len(configs), f"Accuracy against the golden labels ({total} controls)")
    names = [c.name for c in configs]
    values = [c.aggregate.accuracy if c.aggregate else 0.0 for c in configs]
    colours = [cs.primary if i == 0 else cs.muted for i in range(len(configs))]
    ax.barh(names, values, color=colours, height=cs.bar_height)
    ax.set_xlim(0, 1)
    ax.invert_yaxis()
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0", "25 %", "50 %", "75 %", "100 %"])
    for y, v in enumerate(values):
        ax.text(v + 0.012, y, f"{v:.0%}", va="center", color=cs.ink, fontsize=cs.font_size)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return _save(fig, path, cs)


def tokens_chart(results: EvalResults, cs: ChartSettings, path: Path) -> Path:
    """Stacked horizontal bars: LLM tokens in and out per config (Jev tokens are not LLM tokens)."""
    configs = _model_configs(results)
    vendors = len(results.samples)
    fig, ax = _frame(cs, len(configs), f"LLM tokens per config ({vendors} vendors)")
    names = [c.name for c in configs]
    tin = [c.aggregate.tokens_in / 1000 if c.aggregate else 0 for c in configs]
    tout = [c.aggregate.tokens_out / 1000 if c.aggregate else 0 for c in configs]
    ax.barh(
        names,
        tin,
        color=cs.primary,
        height=cs.bar_height,
        label="tokens in",
        edgecolor=cs.surface,
        linewidth=2,
    )
    ax.barh(
        names,
        tout,
        left=tin,
        color=cs.secondary,
        height=cs.bar_height,
        label="tokens out",
        edgecolor=cs.surface,
        linewidth=2,
    )
    ax.invert_yaxis()
    ax.set_xlabel("thousand tokens", color=cs.ink_secondary)
    top = max(a + b for a, b in zip(tin, tout, strict=True))
    ax.set_xlim(0, top * 1.14)
    for y, (a, b) in enumerate(zip(tin, tout, strict=True)):
        ax.text(
            a + b + top * 0.01,
            y,
            f"{a + b:,.0f}k",
            va="center",
            color=cs.ink,
            fontsize=cs.font_size,
        )
    ax.legend(frameon=False, loc="lower right", labelcolor=cs.ink_secondary)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return _save(fig, path, cs)


def confusion_chart(results: EvalResults, cs: ChartSettings, path: Path) -> Path:
    """Pooled confusion matrix (golden rows, system columns) of the best model config."""
    best = _model_configs(results)[0]
    counts = [[0] * len(PRED_LABELS) for _ in GOLD_LABELS]
    for run in best.runs:
        if run.metrics:
            for i, g in enumerate(GOLD_LABELS):
                for j, p in enumerate(PRED_LABELS):
                    counts[i][j] += run.metrics.confusion[g][p]
    fig, ax = plt.subplots(figsize=(cs.cell_in * len(PRED_LABELS) + 1.6, cs.cell_in * 4 + 1.2))
    fig.patch.set_facecolor(cs.surface)
    fig.suptitle(
        f"Golden vs system status: {best.name}",
        x=0.02,
        ha="left",
        fontsize=cs.title_size,
        color=cs.ink,
        fontweight="bold",
    )
    cmap = LinearSegmentedColormap.from_list("blue", cs.ramp)
    top = max(max(row) for row in counts) or 1
    ax.imshow(counts, cmap=cmap, vmin=0, vmax=top)
    ax.set_xticks(range(len(PRED_LABELS)), [p.replace("_", "\n") for p in PRED_LABELS])
    ax.set_yticks(range(len(GOLD_LABELS)), [g.replace("_", " ") for g in GOLD_LABELS])
    ax.set_xlabel("system", color=cs.ink_secondary)
    ax.set_ylabel("golden", color=cs.ink_secondary)
    ax.tick_params(colors=cs.ink_secondary, length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(PRED_LABELS))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(GOLD_LABELS))], minor=True)
    ax.grid(which="minor", color=cs.surface, linewidth=2)
    ax.tick_params(which="minor", length=0)
    for i, row in enumerate(counts):
        for j, n in enumerate(row):
            dark = n / top > cs.contrast_threshold
            ax.text(
                j,
                i,
                str(n),
                ha="center",
                va="center",
                fontsize=cs.font_size + 1,
                color=cs.surface if dark else cs.ink,
            )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return _save(fig, path, cs)


def render_charts(results: EvalResults, cs: ChartSettings, out_dir: Path) -> list[Path]:
    """Write the three PNGs into ``out_dir``; returns the paths."""
    return [
        accuracy_chart(results, cs, out_dir / FILES["accuracy"]),
        tokens_chart(results, cs, out_dir / FILES["tokens"]),
        confusion_chart(results, cs, out_dir / FILES["confusion"]),
    ]


__all__ = ["FILES", "accuracy_chart", "confusion_chart", "render_charts", "tokens_chart"]
