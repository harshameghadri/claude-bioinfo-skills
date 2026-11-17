#!/usr/bin/env python3
"""Check that the colours of a palette stay distinguishable for colour-vision deficiencies.

For each colour-vision model (normal, protanopia, deuteranopia, tritanopia) the colours are simulated
(Machado, Oliveira & Fernandes 2009, severity 1.0, applied in linear sRGB), converted to CIELAB (D65) and the smallest pairwise CIE76
distance (Delta E) is reported. A pair closer than --min-delta under any model fails.
This is a screening heuristic, not a medical simulation: Delta E 76 is crude and the threshold is a rule of thumb
(about 10-20 is "distinct side by side"; small marks and thin lines need more). Check the figure itself too.

Usage:  palette_check.py --palette okabe-ito
        palette_check.py --colors "#E69F00,#56B4E9,#009E73" [--min-delta 15]
Exit codes: 0 ok, 2 usage/bad colour, 4 a pair is too close under some model.
Standard library only.
"""
import argparse, itertools, math, re, sys

PALETTES = {
    "okabe-ito": ["#000000", "#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7"],
}
# Machado et al. 2009, severity 1.0, row-major, operate on linear RGB.
MODELS = {
    "normal": None,
    "protanopia": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deuteranopia": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritanopia": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


def parse_hex(c):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", c.strip())
    if not m:
        raise ValueError(f"not a 6-digit hex colour: {c!r}")
    h = m.group(1)
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def to_linear(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def lab(rgb_lin):
    r, g, b = rgb_lin
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    xn, yn, zn = 0.95047, 1.0, 1.08883
    f = lambda t: t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def simulate(rgb_lin, mat):
    if mat is None:
        return rgb_lin
    out = [sum(mat[i][j] * rgb_lin[j] for j in range(3)) for i in range(3)]
    return [min(1.0, max(0.0, v)) for v in out]


def delta_e(a, b):
    return math.dist(a, b)


def analyse(colors):
    res = {}
    lin = [[to_linear(v) for v in parse_hex(c)] for c in colors]
    for name, mat in MODELS.items():
        labs = [lab(simulate(c, mat)) for c in lin]
        pairs = [(delta_e(labs[i], labs[j]), i, j) for i, j in itertools.combinations(range(len(colors)), 2)]
        res[name] = min(pairs) if pairs else (float("inf"), 0, 0)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--palette", choices=sorted(PALETTES))
    g.add_argument("--colors", help="comma separated hex colours")
    ap.add_argument("--min-delta", type=float, default=15.0, help="smallest acceptable pairwise Delta E76 [15]")
    a = ap.parse_args(argv)
    colors = PALETTES[a.palette] if a.palette else [c for c in a.colors.split(",") if c.strip()]
    if len(colors) < 2:
        print("need at least two colours", file=sys.stderr); return 2
    try:
        res = analyse(colors)
    except ValueError as e:
        print(f"palette_check.py: {e}", file=sys.stderr); return 2
    bad = False
    print("model\tmin_delta_e\tclosest_pair\tstatus")
    for name, (d, i, j) in res.items():
        ok = d >= a.min_delta
        bad |= not ok
        print(f"{name}\t{d:.1f}\t{colors[i]} / {colors[j]}\t{'PASS' if ok else 'FAIL'}")
    return 4 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
