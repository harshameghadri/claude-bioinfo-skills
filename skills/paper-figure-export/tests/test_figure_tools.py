"""Offline tests for paper-figure-export (needs Rscript with ggplot2 for the export tests; they are skipped otherwise)."""
import os, shutil, struct, subprocess, sys, tempfile, unittest, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
AUDIT = os.path.join(SKILL, "scripts", "figure_audit.py")
PALETTE = os.path.join(SKILL, "scripts", "palette_check.py")
LIB = os.path.join(SKILL, "scripts", "paper_figure.R")
HAVE_R = shutil.which("Rscript") is not None and subprocess.run(
    ["Rscript", "-e", "q(status=!all(sapply(c('ggplot2','systemfonts'), requireNamespace, quietly=TRUE)))"], capture_output=True).returncode == 0
HAVE_PATCHWORK = HAVE_R and subprocess.run(["Rscript", "-e", "q(status=!requireNamespace('patchwork',quietly=TRUE))"], capture_output=True).returncode == 0


def slurp(path, mode="r"):
    with open(path, mode) as fh:
        return fh.read()


def spit(path, data, mode="w"):
    with open(path, mode) as fh:
        fh.write(data)


def py(script, *args):
    return subprocess.run([sys.executable, "-I", script, *args], capture_output=True, text=True)


def rscript(code):
    return subprocess.run(["Rscript", "-e", code], capture_output=True, text=True)


def make_png(path, w, h, dpi=None):
    def chunk(t, b):
        c = struct.pack(">I", len(b)) + t + b
        return c + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff" * w for _ in range(h))
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
    if dpi:
        ppm = int(round(dpi / 0.0254))
        out += chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
    out += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(out)


class AuditPng(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_pass_when_size_and_dpi_match(self):
        p = os.path.join(self.d, "a.png"); make_png(p, 1051, 800, dpi=300)
        r = py(AUDIT, p, "--expect-width-mm", "89", "--expect-dpi", "300")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_fail_on_wrong_width(self):
        p = os.path.join(self.d, "a.png"); make_png(p, 1051, 800, dpi=300)
        r = py(AUDIT, p, "--expect-width-mm", "183")
        self.assertEqual(r.returncode, 4); self.assertIn("FAIL\tpng-size-mm", r.stdout)

    def test_fail_on_wrong_dpi(self):
        p = os.path.join(self.d, "a.png"); make_png(p, 1051, 800, dpi=72)
        r = py(AUDIT, p, "--expect-dpi", "300")
        self.assertEqual(r.returncode, 4); self.assertIn("png-dpi", r.stdout)

    def test_missing_dpi_metadata_fails_when_dpi_expected(self):
        p = os.path.join(self.d, "a.png"); make_png(p, 1051, 800)
        self.assertEqual(py(AUDIT, p, "--expect-dpi", "300").returncode, 4)

    def test_missing_dpi_metadata_is_skip_without_expectation(self):
        p = os.path.join(self.d, "a.png"); make_png(p, 100, 100)
        r = py(AUDIT, p)
        self.assertEqual(r.returncode, 0); self.assertIn("SKIP\tpng-dpi-metadata", r.stdout)

    def test_max_height(self):
        p = os.path.join(self.d, "a.png"); make_png(p, 1051, 2200, dpi=300)       # 186 mm tall
        self.assertEqual(py(AUDIT, p, "--max-height-mm", "170").returncode, 4)

    def test_not_a_png(self):
        p = os.path.join(self.d, "a.png"); spit(p, b"hello", "wb")
        self.assertEqual(py(AUDIT, p).returncode, 4)

    def test_missing_file_is_error_1(self):
        self.assertEqual(py(AUDIT, os.path.join(self.d, "nope.png")).returncode, 1)

    def test_no_args_is_usage_2(self):
        self.assertEqual(py(AUDIT).returncode, 2)

    def test_svg_size(self):
        p = os.path.join(self.d, "a.svg")
        spit(p, '<svg xmlns="http://www.w3.org/2000/svg" width="89mm" height="60mm"/>')
        self.assertEqual(py(AUDIT, p, "--expect-width-mm", "89").returncode, 0)
        self.assertEqual(py(AUDIT, p, "--expect-width-mm", "183").returncode, 4)


class Palette(unittest.TestCase):
    def test_okabe_ito_passes(self):
        self.assertEqual(py(PALETTE, "--palette", "okabe-ito").returncode, 0)

    def test_red_green_fails_for_deuteranopia(self):
        r = py(PALETTE, "--colors", "#FF0000,#00AA00")
        self.assertEqual(r.returncode, 4); self.assertIn("deuteranopia\t", r.stdout)
        line = [l for l in r.stdout.splitlines() if l.startswith("deuteranopia")][0]
        self.assertTrue(line.endswith("FAIL"))

    def test_identical_colours_fail_everywhere(self):
        r = py(PALETTE, "--colors", "#112233,#112233")
        self.assertEqual(r.returncode, 4); self.assertEqual(r.stdout.count("FAIL"), 4)

    def test_bad_colour_is_usage_error(self):
        self.assertEqual(py(PALETTE, "--colors", "red,blue").returncode, 2)

    def test_single_colour_is_usage_error(self):
        self.assertEqual(py(PALETTE, "--colors", "#112233").returncode, 2)

    def test_lab_reference_values(self):
        sys.path.insert(0, os.path.join(SKILL, "scripts"))
        import palette_check as pc
        L, a, b = pc.lab([pc.to_linear(1.0)] * 3)               # white
        self.assertAlmostEqual(L, 100, delta=0.1); self.assertAlmostEqual(a, 0, delta=0.1); self.assertAlmostEqual(b, 0, delta=0.2)
        L, *_ = pc.lab([0.0, 0.0, 0.0]); self.assertAlmostEqual(L, 0, delta=1e-6)


@unittest.skipUnless(HAVE_R, "R with ggplot2 and systemfonts not available")
class Export(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        code = f'''source("{LIB}"); library(ggplot2)
        p <- ggplot(mtcars, aes(wt, mpg, colour = factor(cyl))) + geom_point() + scale_colour_manual(values = okabe(3, skip_black = TRUE)) + theme_paper()
        pf_save(p, "single", JOURNAL_MM$nature[["single"]], 70, outdir = "{cls.d}", note = "n = 32 cars; each point is one car.")
        pf_save(p, "double", JOURNAL_MM$nature[["double"]], 90, outdir = "{cls.d}", formats = c("pdf", "png", "svg", "tiff"), dpi = 600)'''
        cls.r = rscript(code)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, True)

    def f(self, n):
        return os.path.join(self.d, n)

    def test_export_ran(self):
        self.assertEqual(self.r.returncode, 0, self.r.stderr)

    def test_single_column_png_and_pdf_audit_clean(self):
        r = py(AUDIT, self.f("single.png"), self.f("single.pdf"), "--expect-width-mm", "89", "--expect-height-mm", "70", "--expect-dpi", "300", "--max-height-mm", "170")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_double_column_at_600_dpi(self):
        r = py(AUDIT, self.f("double.png"), self.f("double.pdf"), self.f("double.svg"), "--expect-width-mm", "183", "--expect-dpi", "600")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(os.path.getsize(self.f("double.tiff")) > 0)

    @unittest.skipUnless(shutil.which("pdffonts"), "poppler pdffonts not installed")
    def test_pdf_fonts_are_embedded(self):
        r = py(AUDIT, self.f("single.pdf"))
        self.assertIn("PASS\tpdf-fonts-embedded", r.stdout)

    def test_manifest_lists_every_file_once(self):
        rows = [l.split("\t") for l in slurp(self.f("figure_manifest.tsv")).splitlines()]
        self.assertEqual(rows[0][:3], ["name", "format", "file"])
        self.assertEqual(len(rows) - 1, 6)
        self.assertEqual(len({r[2] for r in rows[1:]}), 6)

    def test_manifest_md5_matches_files(self):
        import hashlib
        for r in [l.split("\t") for l in slurp(self.f("figure_manifest.tsv")).splitlines()][1:]:
            self.assertEqual(hashlib.md5(slurp(self.f(r[2]), "rb")).hexdigest(), r[-1])

    def test_bad_arguments_are_refused(self):
        code = f'source("{LIB}"); library(ggplot2); p <- ggplot(); '
        for call, pat in [('pf_save(p, "a b", 89, 70, outdir = tempdir())', "nzchar|grepl|name"),
                          ('pf_save(p, "x", -1, 70, outdir = tempdir())', "width_mm"),
                          ('pf_save(p, "x", 89, 70, outdir = tempdir(), formats = "bmp")', "unknown format"),
                          ('okabe(9)', "at most 8")]:
            r = rscript(code + call)
            self.assertNotEqual(r.returncode, 0, call)

    def test_unembedded_pdf_is_caught(self):
        if not shutil.which("pdffonts"):
            self.skipTest("pdffonts not installed")
        p = self.f("plain.pdf")
        rscript(f'pdf("{p}", width = 3, height = 2); plot(1:3, main = "x"); dev.off()')
        r = py(AUDIT, p)
        self.assertEqual(r.returncode, 4, r.stdout); self.assertIn("FAIL\tpdf-fonts-embedded", r.stdout)

    def test_theme_sizes(self):
        r = rscript(f'source("{LIB}"); t <- theme_paper(); cat(t$axis.text$size, t$legend.text$size, t$plot.tag$size, t$axis.line$linewidth)')
        self.assertEqual(r.stdout.split(), ["6", "7", "10", "0.3"])

    def test_okabe_has_eight_unique_hex(self):
        r = rscript(f'source("{LIB}"); cat(length(unique(OKABE_ITO)), all(grepl("^#[0-9A-F]{{6}}$", OKABE_ITO)), identical(okabe(3), unname(OKABE_ITO[1:3])))')
        self.assertEqual(r.stdout.split(), ["8", "TRUE", "TRUE"])

    @unittest.skipUnless(HAVE_PATCHWORK, "patchwork not installed")
    def test_composed_figure_exports_with_note(self):
        out = os.path.join(self.d, "comp")
        r = rscript(f'''source("{LIB}"); library(ggplot2); a <- ggplot(mtcars, aes(wt, mpg)) + geom_point() + theme_paper(); b <- a + ggtitle("b")
        fig <- pf_stack(list(pf_row(list(a, b), tags = c("A", "B")), pf_row(list(a), tags = "C")), heights = c(1, 1))
        pf_save(fig, "composed", 183, 120, outdir = "{out}", note = "Composite with a note.")''')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(py(AUDIT, os.path.join(out, "composed.png"), "--expect-width-mm", "183", "--expect-height-mm", "120", "--expect-dpi", "300").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
