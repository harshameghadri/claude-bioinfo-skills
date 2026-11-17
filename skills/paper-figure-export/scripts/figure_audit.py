#!/usr/bin/env python3
"""Audit exported figure files against a size/resolution/font specification.

Checks (per file, by extension):
  PNG  : pixel size, embedded resolution (pHYs chunk), size in mm = pixels / dpi * 25.4
  PDF  : page size in mm (pdfinfo if present, else the /MediaBox), fonts embedded and no Type 3 fonts (pdffonts if present)
  SVG  : root width/height attributes when they carry units (mm, cm, in, pt, px at 96 dpi)
Exit codes: 0 all checks passed (SKIP is not a failure), 1 error, 2 usage, 4 at least one check failed.
Output: one line per check, tab separated: STATUS  check  file  detail      (stdout)
Standard library only; pdfinfo/pdffonts (poppler) are used when installed.
"""
import argparse, os, re, shutil, struct, subprocess, sys, xml.etree.ElementTree as ET

EXIT_FAIL = 4
rows = []


def emit(status, check, path, detail):
    rows.append(status)
    print("\t".join([status, check, os.path.basename(path), detail]))


def png_info(path):
    with open(path, "rb") as fh:
        data = fh.read(1 << 16)
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    i, size, dpi = 8, None, None
    while i + 8 <= len(data):
        n, typ = struct.unpack(">I4s", data[i:i + 8])
        body = data[i + 8:i + 8 + n]
        if typ == b"IHDR":
            size = struct.unpack(">II", body[:8])
        elif typ == b"pHYs" and len(body) == 9:
            px, py, unit = struct.unpack(">IIB", body)
            if unit == 1:
                dpi = (px * 0.0254, py * 0.0254)
        elif typ == b"IDAT":
            break
        i += 12 + n
    if size is None:
        raise ValueError("PNG without IHDR")
    return size, dpi


def audit_png(path, a):
    try:
        (w, h), dpi = png_info(path)
    except Exception as e:
        emit("FAIL", "png-readable", path, str(e)); return
    emit("PASS", "png-readable", path, f"{w}x{h} px")
    if dpi is None:
        emit("FAIL" if a.expect_dpi else "SKIP", "png-dpi-metadata", path, "no pHYs chunk (resolution not recorded)")
        eff = a.expect_dpi
    else:
        eff = dpi[0]
        if a.expect_dpi:
            ok = abs(dpi[0] - a.expect_dpi) <= a.dpi_tol and abs(dpi[1] - a.expect_dpi) <= a.dpi_tol
            emit("PASS" if ok else "FAIL", "png-dpi", path, f"{dpi[0]:.1f} x {dpi[1]:.1f} dpi (expected {a.expect_dpi})")
    if eff:
        wmm, hmm = w / eff * 25.4, h / eff * 25.4
        check_size(path, "png-size-mm", wmm, hmm, a, extra=f"at {eff:.0f} dpi")
    if a.expect_width_mm and a.expect_dpi:
        want = a.expect_width_mm / 25.4 * a.expect_dpi
        emit("PASS" if abs(w - want) <= 1.0 else "FAIL", "png-pixel-width", path, f"{w} px (expected {want:.1f})")


def check_size(path, check, wmm, hmm, a, extra=""):
    ok = True
    if a.expect_width_mm is not None:
        ok &= abs(wmm - a.expect_width_mm) <= a.tol_mm
    if a.expect_height_mm is not None:
        ok &= abs(hmm - a.expect_height_mm) <= a.tol_mm
    if a.max_height_mm is not None:
        ok &= hmm <= a.max_height_mm + a.tol_mm
    detail = f"{wmm:.1f} x {hmm:.1f} mm {extra}".strip()
    if a.expect_width_mm is None and a.expect_height_mm is None and a.max_height_mm is None:
        emit("INFO", check, path, detail)
    else:
        emit("PASS" if ok else "FAIL", check, path, detail)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def pdf_size_mm(path):
    if shutil.which("pdfinfo"):
        r = run(["pdfinfo", path])
        m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", r.stdout)
        if m:
            return float(m.group(1)) / 72 * 25.4, float(m.group(2)) / 72 * 25.4
    with open(path, "rb") as fh:
        raw = fh.read()
    m = re.search(rb"/MediaBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\]", raw)
    if not m:
        return None
    x0, y0, x1, y1 = (float(g) for g in m.groups())
    return (x1 - x0) / 72 * 25.4, (y1 - y0) / 72 * 25.4


def audit_pdf(path, a):
    try:
        with open(path, "rb") as fh:
            if fh.read(5) != b"%PDF-":
                raise ValueError("not a PDF file")
    except Exception as e:
        emit("FAIL", "pdf-readable", path, str(e)); return
    emit("PASS", "pdf-readable", path, "")
    sz = pdf_size_mm(path)
    if sz is None:
        emit("SKIP", "pdf-size-mm", path, "page size not found (compressed object stream and no pdfinfo)")
    else:
        check_size(path, "pdf-size-mm", sz[0], sz[1], a)
    if not shutil.which("pdffonts"):
        emit("SKIP", "pdf-fonts", path, "pdffonts (poppler-utils) not installed; fonts not verified")
        return
    r = run(["pdffonts", path])
    lines = [l for l in r.stdout.splitlines()[2:] if l.strip()]
    if r.returncode != 0:
        emit("FAIL", "pdf-fonts", path, (r.stderr.strip() or "pdffonts failed")); return
    if not lines:
        emit("PASS", "pdf-fonts", path, "no fonts used (text drawn as paths or no text)"); return
    bad, t3 = [], []
    for l in lines:
        m = re.search(r"\s(Type 3|Type 1C?|CID Type 0C?|CID TrueType|TrueType|Type 1|OpenType|CID Type 0)\s+\S+\s+(yes|no)\s+(yes|no)\s+(yes|no)", l)
        name = l.split()[0]
        if not m:
            continue
        if m.group(1) == "Type 3":
            t3.append(name)
        if m.group(2) == "no":
            bad.append(name)
    emit("FAIL" if bad else "PASS", "pdf-fonts-embedded", path, ("not embedded: " + ", ".join(bad)) if bad else f"{len(lines)} font(s), all embedded")
    if a.forbid_type3:
        emit("FAIL" if t3 else "PASS", "pdf-no-type3", path, ("Type 3 fonts: " + ", ".join(t3)) if t3 else "none")


def svg_len_mm(v):
    m = re.fullmatch(r"\s*([\d.]+)\s*(mm|cm|in|pt|px)?\s*", v or "")
    if not m:
        return None
    x, u = float(m.group(1)), m.group(2) or "px"
    return {"mm": x, "cm": x * 10, "in": x * 25.4, "pt": x / 72 * 25.4, "px": x / 96 * 25.4}[u]


def audit_svg(path, a):
    try:
        root = ET.parse(path).getroot()
    except Exception as e:
        emit("FAIL", "svg-readable", path, str(e)); return
    emit("PASS", "svg-readable", path, "")
    w, h = svg_len_mm(root.get("width")), svg_len_mm(root.get("height"))
    if w is None or h is None:
        emit("SKIP", "svg-size-mm", path, "width/height missing or not absolute"); return
    check_size(path, "svg-size-mm", w, h, a, extra="(px taken as 1/96 in)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="figure files (.png .pdf .svg)")
    ap.add_argument("--expect-width-mm", type=float)
    ap.add_argument("--expect-height-mm", type=float)
    ap.add_argument("--max-height-mm", type=float, help="fail when taller than this (e.g. 170 for a Nature figure with legend)")
    ap.add_argument("--tol-mm", type=float, default=1.0, help="size tolerance [1.0]")
    ap.add_argument("--expect-dpi", type=float, help="required resolution for raster files")
    ap.add_argument("--dpi-tol", type=float, default=1.0)
    ap.add_argument("--no-type3-check", dest="forbid_type3", action="store_false", help="do not fail on Type 3 fonts in PDFs")
    a = ap.parse_args(argv)
    for f in a.files:
        if not os.path.isfile(f):
            print(f"figure_audit.py: no such file: {f}", file=sys.stderr); return 1
        ext = os.path.splitext(f)[1].lower()
        try:
            {".png": audit_png, ".pdf": audit_pdf, ".svg": audit_svg}[ext](f, a)
        except KeyError:
            emit("SKIP", "format", f, f"unsupported extension {ext or '(none)'}")
        except Exception as e:  # unexpected: report, do not crash silently
            emit("FAIL", "audit-error", f, repr(e))
    return EXIT_FAIL if "FAIL" in rows else 0


if __name__ == "__main__":
    sys.exit(main())
