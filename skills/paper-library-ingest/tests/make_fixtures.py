#!/usr/bin/env python3
"""Write small synthetic PDFs (no third-party packages) for the offline tests.
Usage: make_fixtures.py OUTDIR      Creates paper-like PDFs (text on page 1 and body pages), plus one non-science invoice.
Exit codes: 0 ok, 2 usage."""
import os, sys


def make_pdf(path, pages):
    """pages: list of lists of text lines. Writes an uncompressed PDF that pdftotext can read."""
    objs = []
    def add(b): objs.append(b); return len(objs)
    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"")  # placeholder for the page tree
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for lines in pages:
        esc = lambda t: t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = "BT /F1 10 Tf 12 TL 50 750 Td " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
        c = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode("latin-1", "replace"))
        kids.append(add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {c} 0 R /Resources << /Font << /F1 {font} 0 R >> >> >>".encode()))
    objs[1] = f"<< /Type /Pages /Count {len(kids)} /Kids [{' '.join(f'{k} 0 R' for k in kids)}] >>".encode()
    out = bytearray(b"%PDF-1.4\n"); offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out); out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for o in offs: out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    with open(path, "wb") as f: f.write(out)


def paper(path, title, authors, abstract, journal="Journal of Synthetic Examples", doi="10.5555/test.0001", year=2026, pages=5, tag=""):
    first = [title, authors, f"{journal}. Received 3 March {year}; accepted 9 May {year}; published {year}.", f"doi:{doi}", "Abstract", *abstract, "Keywords: " + (tag or "example, test")]
    body = ["Introduction", *abstract, "Methods and results are described here in detail.", "References", "1. Author A et al. Another paper. 2020."]
    make_pdf(path, [first] + [body] * (pages - 1))


def main(argv):
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        print(__doc__); return 0 if len(argv) == 2 else 2
    d = argv[1]; os.makedirs(d, exist_ok=True)
    q = ["Quantum coherence and electron tunneling in photosynthetic light harvesting complexes and avian magnetoreception radical pair mechanism."]
    paper(f"{d}/qb1.pdf", "Quantum coherence in photosynthetic light harvesting complexes", "Anna Meyer, Bo Li and Carl Jones", q, tag="quantum biology, coherence")
    paper(f"{d}/qb2.pdf", "Radical pair mechanism and avian magnetoreception quantum effects in biology", "Dana Kowalski, Eli Roth", q + ["Radical pair spin dynamics cryptochrome magnetoreception."], doi="10.5555/test.0002")
    paper(f"{d}/qb3.pdf", "Electron tunneling and quantum coherence in enzyme catalysis", "Farah Nasser, Gil Park", q + ["Proton tunneling enzyme catalysis coherence."], doi="10.5555/test.0003")
    paper(f"{d}/sc1.pdf", "Spatial transcriptomics deconvolution of tissue sections", "Hugo Brandt, Ines Cole", ["Spatial transcriptomics deconvolution method for Visium tissue sections with cell type reference."], doi="10.5555/test.0004")
    make_pdf(f"{d}/Rechnung_2026_11.pdf", [["Rechnung Nr 4711", "Stadtwerke", "Betrag 120 EUR", "Kontoauszug IBAN"] * 8, ["Zahlung bis 30.11."] * 20])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
