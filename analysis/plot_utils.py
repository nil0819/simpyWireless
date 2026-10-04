# Rashed-Step 14.A-08-28-2026-start
"""
Shared plotting helper for every figure-generation script in analysis/.
Every figure goes through save_line_figure() so all of the paper's
figures share one consistent, publication-quality look: gridded,
bordered (visible spines on all four sides), a fixed per-series
color/marker/linestyle registry (so a given technology - or a given
technology's model-vs-simulated pair - is drawn identically across every
figure this module produces), a legend, and high-resolution PDF+JPG
output into analysis/generated/.
"""
import os
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")  # headless - this module never opens an interactive window
import matplotlib.pyplot as plt
import numpy as np

# Rashed-Step 14.J-08-30-2026-start
# Rashed asked whether the figures use Times New Roman - they didn't
# (matplotlib's default is DejaVu Sans, a sans-serif font), and asked
# to switch. The actual "Times New Roman" font file is a proprietary
# Microsoft font not present on this Linux sandbox, so this uses
# "Liberation Serif" - a metrically-compatible, freely-licensed clone
# of Times New Roman (same glyph widths/spacing, near-identical
# appearance) commonly used as its drop-in substitute on Linux/LaTeX
# toolchains, matching the serif look IEEE-style papers expect. Falls
# back to "Nimbus Roman" (another Times-compatible URW clone) then
# plain "serif" (whatever the system default serif is) if Liberation
# Serif isn't installed in a given environment, so this degrades
# gracefully rather than failing outright. Set globally via rcParams
# once, at import time, so every figure this module produces (all 12
# line-figures plus the 2 bar-chart figures) picks it up automatically
# with no per-script change needed.
plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = ["Liberation Serif", "Nimbus Roman", "Times New Roman", "serif"]
plt.rcParams["mathtext.fontset"] = "stix"  # Times-like math glyphs, to match the text font
# Rashed-Step 14.J-08-30-2026-end

GENERATED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)

# One style per series LABEL, reused across every figure this module
# generates - keeps a technology visually identical (same color + marker)
# whether it's plotted alone, against its analytical model, or against
# the other technology, so a reader flipping between the paper's figures
# doesn't have to re-learn the legend each time. Model-vs-simulated (and
# short-vs-long-TXOP) pairs share BOTH color and marker now and differ
# only by linestyle (dashed=model, solid=simulated/measured) - see Step
# 14.H below for why marker is no longer used to distinguish variants.
# Rashed-Step 14.G-08-29-2026-start
# Rashed's fixed brand colors (2026-08-29): every Wi-Fi series uses
# #111184 (navy), every NR-U series uses #4b7248 (green), regardless of
# variant (Model/Simulated/Long TXOP) - variants differentiate by
# linestyle only now (see 14.H), so "Wi-Fi" always reads as the same
# color across every figure in this module. Non-technology series
# (Fairness Index, Combined) are intentionally left on their own
# colors - Rashed's request was specifically "for NR-U"/"for Wi-Fi".
WIFI_COLOR = "#111184"
NRU_COLOR = "#4b7248"
# Rashed-Step 14.G-08-29-2026-end
# Rashed-Step 14.H-08-29-2026-start
# Rashed flagged that Wi-Fi's square ("s") and NR-U's diamond ("D")
# markers looked too similar (both 4-sided) once every series across a
# figure also shared linestyle conventions - asked for a shape family
# that's unambiguous at a glance, used CONSISTENTLY for every Wi-Fi/
# NR-U variant (Model, Simulated, Long TXOP) rather than a different
# shape per variant - variants differ only by linestyle (dashed vs
# solid), never by marker shape, so whichever Wi-Fi/NR-U shapes are
# chosen hold everywhere in this module, no exceptions. Originally set
# to square ("s") for Wi-Fi / triangle ("^") for NR-U - see Step 14.I
# below for the follow-up change to the shapes actually in effect now.
# Rashed-Step 14.H-08-29-2026-end
# Rashed-Step 14.I-08-29-2026-start
# Rashed asked to swap the shapes: triangle for Wi-Fi, hexagon for
# NR-U (instead of 14.H's original square-for-Wi-Fi/triangle-for-NR-U).
# Same "one shape per technology, every variant, no exceptions" rule
# as 14.H - only the two shapes themselves changed.
WIFI_MARKER = "^"  # triangle
NRU_MARKER = "h"   # hexagon
# Rashed-Step 14.I-08-29-2026-end
SERIES_STYLE: Dict[str, dict] = {
    "Wi-Fi (Model)":     dict(color=WIFI_COLOR, marker=WIFI_MARKER, linestyle="--"),
    "Wi-Fi (Simulated)": dict(color=WIFI_COLOR, marker=WIFI_MARKER, linestyle="-"),
    "NR-U (Model)":      dict(color=NRU_COLOR, marker=NRU_MARKER, linestyle="--"),
    "NR-U (Simulated)":  dict(color=NRU_COLOR, marker=NRU_MARKER, linestyle="-"),
    "Wi-Fi":             dict(color=WIFI_COLOR, marker=WIFI_MARKER, linestyle="-"),
    "NR-U":              dict(color=NRU_COLOR, marker=NRU_MARKER, linestyle="-"),
    "Fairness Index":    dict(color="#2ca02c", marker="o", linestyle="-"),
    # Rashed-Step 14.B-08-28-2026-start
    "Combined (Wi-Fi + NR-U)": dict(color="#7f7f7f", marker="x", linestyle="-"),
    # Rashed-Step 14.B-08-28-2026-end
    # Rashed-Step 14.C-08-28-2026-start
    "Wi-Fi (Long TXOP)": dict(color=WIFI_COLOR, marker=WIFI_MARKER, linestyle="-"),
    # Rashed-Step 14.C-08-28-2026-end
}

LINEWIDTH = 2.2
MARKERSIZE = 8
MARKEREDGEWIDTH = 1.3
FONTSIZE_LABEL = 18
FONTSIZE_TITLE = 14
FONTSIZE_TICK = 16
FONTSIZE_LEGEND = 14
DPI = 300  # high resolution - safe for both print and screen viewing


def save_line_figure(
    x: Sequence[float],
    series: Dict[str, Sequence[float]],
    xlabel: str,
    ylabel: str,
    title: str,
    output_stem: str,
    x_ticks_as_int: bool = True,
    figsize=(7.5, 5.5),
    # Rashed-Step 14.B-08-28-2026-start
    xscale: str = "linear",
    hlines: Optional[List[Tuple[float, str]]] = None,
    vlines: Optional[List[Tuple[float, str]]] = None,
    # Rashed-Step 14.B-08-28-2026-end
    # Rashed-Step 14.L-08-31-2026-start
    yerr: Optional[Dict[str, Sequence[float]]] = None,
    # Rashed-Step 14.L-08-31-2026-end
) -> Dict[str, str]:
    """
    Draws one gridded, bordered line plot - one line per (label, y-values)
    pair in `series`, styled per SERIES_STYLE (falls back to matplotlib's
    default color/marker cycle for any label not in the registry, so this
    still works for one-off series names) - and saves it as both a vector
    PDF and a high-resolution (300 DPI) JPG under analysis/generated/.

    output_stem: filename WITHOUT extension or directory, e.g.
      "occupancy_model_vs_simulation" ->
        analysis/generated/occupancy_model_vs_simulation.pdf
        analysis/generated/occupancy_model_vs_simulation.jpg

    xscale: "linear" (default, unchanged from before Step 14.B) or "log" -
      useful for a wide-range distance sweep (e.g. the sensing-region
      figure) where a linear axis would crowd every interesting point
      into the first few pixels.
    hlines/vlines: optional list of (value, label) reference lines drawn
      as thin dashed lines with their own legend entries (e.g. a y=1.0
      "shared channel" reference, or vertical markers at an
      analytically-derived sensing-range crossover distance) - purely
      additive, no effect on any existing caller that doesn't pass them.
    yerr: optional {label: half-width-per-x-point} dict (e.g. a 95% CI
      half-width from repeated-seed sweeps). Only series present as a key
      in `yerr` get error bars (via ax.errorbar); every other series is
      still drawn with plain ax.plot as before - so this is purely
      additive and every existing caller (yerr=None, the default) is
      byte-identical to before this parameter existed.

    Returns {"pdf": <path>, "jpg": <path>}.
    """
    fig, ax = plt.subplots(figsize=figsize)

    for label, y in series.items():
        style = SERIES_STYLE.get(label, {})
        # Rashed-Step 14.L-08-31-2026-start
        series_yerr = (yerr or {}).get(label)
        if series_yerr is not None:
            ax.errorbar(
                x, y, yerr=series_yerr,
                label=label,
                linewidth=LINEWIDTH,
                markersize=MARKERSIZE,
                markeredgewidth=MARKEREDGEWIDTH,
                markerfacecolor="white",
                capsize=4, capthick=1.3, elinewidth=1.3,
                **style,
            )
            continue
        # Rashed-Step 14.L-08-31-2026-end
        ax.plot(
            x, y,
            label=label,
            linewidth=LINEWIDTH,
            markersize=MARKERSIZE,
            markeredgewidth=MARKEREDGEWIDTH,
            markerfacecolor="white",
            **style,
        )

    # Rashed-Step 14.B-08-28-2026-start
    for y_val, y_label in (hlines or []):
        ax.axhline(y_val, color="black", linestyle=":", linewidth=1.4, alpha=0.8, label=y_label)
    for x_val, x_label in (vlines or []):
        ax.axvline(x_val, color="#9467bd", linestyle="-.", linewidth=1.4, alpha=0.8, label=x_label)
    # Rashed-Step 14.B-08-28-2026-end

    ax.set_xlabel(xlabel, fontsize=FONTSIZE_LABEL)
    ax.set_ylabel(ylabel, fontsize=FONTSIZE_LABEL)
    # Rashed-Step 14.F-08-29-2026-start
    # Rashed asked to drop titles from every figure in this module (the
    # paper will caption each figure itself) - `title` is still accepted
    # for backward compatibility with every caller's signature/tests, but
    # is intentionally never rendered on the axes anymore.
    # Rashed-Step 14.F-08-29-2026-end
    ax.tick_params(axis="both", labelsize=FONTSIZE_TICK)

    # Rashed-Step 14.B-08-28-2026-start
    if xscale != "linear":
        ax.set_xscale(xscale)
    # Rashed-Step 14.B-08-28-2026-end

    if x_ticks_as_int:
        ax.set_xticks(list(x))

    # Gridded.
    ax.grid(True, which="major", linestyle=":", linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)  # grid behind the data lines, not on top of them

    # Bordered - visible, print-legible spines on all four sides.
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(1.2)
        spine.set_color("black")

    ax.legend(fontsize=FONTSIZE_LEGEND, framealpha=0.9, edgecolor="black")

    fig.tight_layout()

    pdf_path = os.path.join(GENERATED_DIR, f"{output_stem}.pdf")
    jpg_path = os.path.join(GENERATED_DIR, f"{output_stem}.jpg")
    fig.savefig(pdf_path, dpi=DPI, bbox_inches="tight")
    fig.savefig(jpg_path, dpi=DPI, bbox_inches="tight", format="jpg")
    plt.close(fig)

    return {"pdf": pdf_path, "jpg": jpg_path}
# Rashed-Step 14.A-08-28-2026-end


# Rashed-Step 13.F-08-29-2026-start
# Consistent "baseline/heuristic" vs "ML-driven" color pair, reused
# across BOTH ml/ performance-evaluation figures (prediction-accuracy
# bar chart and PDR-comparison bar chart) so a reader learns the
# mapping once: gray always means "the simple, non-learned baseline"
# (persistence / last-measured-SINR heuristic), orange always means
# "the trained model's prediction is driving the decision" (learned
# SINR predictor / ML-driven rate adaptation). Orange (#ff7f0e) was
# freed up by Step 14.G (it used to be "Wi-Fi (Long TXOP)"'s color,
# before 14.G unified all Wi-Fi series onto navy) - reused here rather
# than introducing a new hue, and it's unambiguous in these bar charts
# since Wi-Fi/NR-U's navy/green never appear as bar colors themselves
# (they're x-axis category labels here, not series).
BASELINE_COLOR = "#7f7f7f"
ML_COLOR = "#ff7f0e"
BAR_STYLE: Dict[str, str] = {
    "Persistence": BASELINE_COLOR,
    "Heuristic": BASELINE_COLOR,
    "Model": ML_COLOR,
    "ML-Driven": ML_COLOR,
}


def save_bar_figure(
    categories: Sequence[str],
    series: Dict[str, Sequence[float]],
    xlabel: str,
    ylabel: str,
    output_stem: str,
    figsize=(8.0, 5.5),
    value_fmt: str = "{:.2f}",
    value_labels: bool = True,
    bar_colors: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    Grouped bar chart - one group per category (x-axis), one bar per
    (label, values) pair in `series` within each group, styled per
    BAR_STYLE (falls back to matplotlib's default color cycle for any
    label not in the registry). Same gridded/bordered/no-title/
    PDF+JPG-at-300-DPI conventions as save_line_figure(), just for
    categorical (not x-y line) comparisons - e.g. persistence vs a
    trained model's MAE/RMSE, or a heuristic vs an ML-driven policy's
    packet delivery ratio, across a handful of named scenarios.

    Returns {"pdf": <path>, "jpg": <path>}.
    """
    fig, ax = plt.subplots(figsize=figsize)

    n_series = len(series)
    x = np.arange(len(categories))
    bar_width = 0.8 / max(n_series, 1)

    for i, (label, values) in enumerate(series.items()):
        color = (bar_colors or BAR_STYLE).get(label, None)
        offset = (i - (n_series - 1) / 2) * bar_width
        bars = ax.bar(
            x + offset, values, width=bar_width * 0.92, label=label,
            color=color, edgecolor="black", linewidth=1.0,
        )
        if value_labels:
            for rect, v in zip(bars, values):
                ax.annotate(
                    value_fmt.format(v),
                    xy=(rect.get_x() + rect.get_width() / 2, rect.get_height()),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9,
                )

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=FONTSIZE_TICK)
    ax.set_xlabel(xlabel, fontsize=FONTSIZE_LABEL)
    ax.set_ylabel(ylabel, fontsize=FONTSIZE_LABEL)
    ax.tick_params(axis="y", labelsize=FONTSIZE_TICK)

    ax.grid(True, axis="y", which="major", linestyle=":", linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(1.2)
        spine.set_color("black")

    ax.legend(fontsize=FONTSIZE_LEGEND, framealpha=0.9, edgecolor="black")

    fig.tight_layout()

    pdf_path = os.path.join(GENERATED_DIR, f"{output_stem}.pdf")
    jpg_path = os.path.join(GENERATED_DIR, f"{output_stem}.jpg")
    fig.savefig(pdf_path, dpi=DPI, bbox_inches="tight")
    fig.savefig(jpg_path, dpi=DPI, bbox_inches="tight", format="jpg")
    plt.close(fig)

    return {"pdf": pdf_path, "jpg": jpg_path}
# Rashed-Step 13.F-08-29-2026-end


# Rashed-Step 16.G-10-04-2026-start
# Stacked bars for "how a total breaks down into stages" (Step 16.G's
# RRC / registration / PDU session attach breakdown). The stages are not
# technologies, so they deliberately don't use WIFI_COLOR/NRU_COLOR -
# technologies stay on the x-axis as categories, same as save_bar_figure.
# Neutral grays plus a hatch per stage keep the stages distinguishable
# in black-and-white print.
STACK_STYLE: Dict[str, dict] = {
    "RRC setup":           dict(color="#404040", hatch=""),
    "Registration":        dict(color="#9a9a9a", hatch="//"),
    "PDU session":         dict(color="#e0e0e0", hatch=".."),
}


def save_stacked_bar_figure(
    categories: Sequence[str],
    stacks: Dict[str, Sequence[float]],
    xlabel: str,
    ylabel: str,
    output_stem: str,
    figsize=(8.0, 5.5),
    value_fmt: str = "{:.1f}",
    total_labels: bool = True,
) -> Dict[str, str]:
    """
    One stacked bar per category; `stacks` is {stage label: one value per
    category}, drawn bottom-up in dict order and styled per STACK_STYLE
    (matplotlib defaults for unknown labels). Optionally labels each bar
    with its total. Same gridded/bordered/no-title/PDF+JPG-at-300-DPI
    conventions as save_bar_figure().

    Returns {"pdf": <path>, "jpg": <path>}.
    """
    fig, ax = plt.subplots(figsize=figsize)
    x = np.arange(len(categories))
    bottoms = np.zeros(len(categories))

    for label, values in stacks.items():
        style = STACK_STYLE.get(label, {})
        values = np.asarray(values, dtype=float)
        ax.bar(
            x, values, width=0.6, bottom=bottoms, label=label,
            color=style.get("color"), hatch=style.get("hatch", ""),
            edgecolor="black", linewidth=1.0,
        )
        bottoms = bottoms + values

    if total_labels:
        for xi, total in zip(x, bottoms):
            ax.annotate(
                value_fmt.format(total),
                xy=(xi, total), xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=FONTSIZE_LEGEND,
            )
    # Headroom above the tallest bar for its total label plus the
    # one-row legend along the top (see below), so neither ever
    # overlaps a bar.
    ax.set_ylim(0, bottoms.max() * 1.30 if len(bottoms) else 1)

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=FONTSIZE_TICK)
    ax.set_xlabel(xlabel, fontsize=FONTSIZE_LABEL)
    ax.set_ylabel(ylabel, fontsize=FONTSIZE_LABEL)
    ax.tick_params(axis="y", labelsize=FONTSIZE_TICK)

    ax.grid(True, axis="y", which="major", linestyle=":", linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(1.2)
        spine.set_color("black")

    # One row across the top, in stacking order (bottom stage first), in
    # the headroom reserved above - a corner legend covered the bottom
    # slice of the last bar.
    ax.legend(fontsize=FONTSIZE_LEGEND, framealpha=0.9, edgecolor="black",
              loc="upper center", ncol=len(stacks))

    fig.tight_layout()

    pdf_path = os.path.join(GENERATED_DIR, f"{output_stem}.pdf")
    jpg_path = os.path.join(GENERATED_DIR, f"{output_stem}.jpg")
    fig.savefig(pdf_path, dpi=DPI, bbox_inches="tight")
    fig.savefig(jpg_path, dpi=DPI, bbox_inches="tight", format="jpg")
    plt.close(fig)

    return {"pdf": pdf_path, "jpg": jpg_path}
# Rashed-Step 16.G-10-04-2026-end
