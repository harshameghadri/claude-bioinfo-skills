"""Offline tests for dataset-audit. Synthetic files only."""
import gzip, hashlib, os, random, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "dataset_audit.py")


def audit(*args):
    r = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True)
    lines = [l.split("\t") for l in r.stdout.splitlines() if l.strip()]
    return r.returncode, lines, r.stderr


def has(lines, sev, check):
    return any(l[0] == sev and l[1] == check for l in lines)


def write(path, data, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as fh:
        fh.write(data)


def write_gz(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt") as fh:
        fh.write(text)


def fastq_text(n, seed=1, mate=1, qual_len_error=False, names=None):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        seq = "".join(rnd.choice("ACGT") for _ in range(20))
        nm = names[i] if names else f"read{i}"
        out.append(f"@{nm} {mate}:N:0\n{seq}\n+\n{'I' * (19 if qual_len_error and i == n - 1 else 20)}\n")
    return "".join(out)


def mtx_text(nr, nc, entries, field="integer"):
    body = "".join(f"{i} {j} {v}\n" for i, j, v in entries)
    return f"%%MatrixMarket matrix coordinate {field} general\n%\n{nr} {nc} {len(entries)}\n{body}"


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def p(self, *a):
        return os.path.join(self.d, *a)


class Inventory(Base):
    def test_clean_directory_passes(self):
        write_gz(self.p("a.txt.gz"), "hello\n"); write(self.p("b.txt"), "x")
        rc, lines, _ = audit("inventory", self.d)
        self.assertEqual(rc, 0, lines)

    def test_zero_byte_and_incomplete_markers(self):
        write(self.p("empty.txt"), ""); write(self.p("x.fastq.gz"), "partial"); write(self.p("x.fastq.gz.aria2"), "ctl")
        rc, lines, _ = audit("inventory", self.d, "--gz-test", "none")
        self.assertEqual(rc, 4)
        self.assertTrue(has(lines, "ERROR", "zero-byte")); self.assertTrue(has(lines, "ERROR", "incomplete-download"))

    def test_truncated_gzip_detected_in_full_mode(self):
        write_gz(self.p("t.txt.gz"), "line\n" * 20000)
        with open(self.p("t.txt.gz"), "rb") as fh:
            raw = fh.read()
        write(self.p("t.txt.gz"), raw[:len(raw) // 2], "wb")
        rc, lines, _ = audit("inventory", self.d)
        self.assertEqual(rc, 4); self.assertTrue(has(lines, "ERROR", "gzip-corrupt"))

    def test_md5_list_match_and_mismatch(self):
        write(self.p("a.txt"), "alpha"); write(self.p("sub", "b.txt"), "beta")
        good = hashlib.md5(b"alpha").hexdigest(); bad = "0" * 32
        write(self.p("..md5"), f"{good}  a.txt\n{bad}  sub/b.txt\n")
        rc, lines, _ = audit("inventory", self.d, "--md5-list", self.p("..md5"))
        self.assertEqual(rc, 4)
        self.assertTrue(has(lines, "OK", "md5")); self.assertTrue(has(lines, "ERROR", "md5"))

    def test_files_tsv_manifest_and_missing_file(self):
        write(self.p("run1", "R_1.fastq.gz"), "abc")
        write(self.p("m.tsv"), "run\tdest_dir\tfilename\turl\tmd5\tbytes\nR\trun1\tR_1.fastq.gz\tu\t%s\t3\nR\trun1\tR_2.fastq.gz\tu\t%s\t3\n" % ((hashlib.md5(b"abc").hexdigest(),) * 2))
        rc, lines, _ = audit("inventory", self.d, "--files-tsv", self.p("m.tsv"), "--gz-test", "none")
        self.assertEqual(rc, 4)
        self.assertTrue(has(lines, "ERROR", "missing-file"))

    def test_identical_content_warns(self):
        write(self.p("a.txt"), "same"); write(self.p("b.txt"), "same")
        rc, lines, _ = audit("inventory", self.d, "--md5")
        self.assertEqual(rc, 0); self.assertTrue(has(lines, "WARN", "identical-content"))
        self.assertEqual(audit("--strict", "inventory", self.d, "--md5")[0], 4)

    def test_empty_dir_is_error(self):
        self.assertEqual(audit("inventory", self.d)[0], 4)


class Fastq(Base):
    def test_good_pair(self):
        write_gz(self.p("S_R1.fastq.gz"), fastq_text(50)); write_gz(self.p("S_R2.fastq.gz"), fastq_text(50, 2, 2))
        rc, lines, _ = audit("fastq", self.d)
        self.assertEqual(rc, 0, lines); self.assertTrue(has(lines, "OK", "mate-count"))

    def test_sra_style_names(self):
        write_gz(self.p("SRR1_1.fastq.gz"), fastq_text(10)); write_gz(self.p("SRR1_2.fastq.gz"), fastq_text(10, 2, 2))
        self.assertEqual(audit("fastq", self.d)[0], 0)

    def test_unequal_mates(self):
        write_gz(self.p("S_R1.fastq.gz"), fastq_text(50)); write_gz(self.p("S_R2.fastq.gz"), fastq_text(49, 2, 2))
        rc, lines, _ = audit("fastq", self.d)
        self.assertEqual(rc, 4); self.assertTrue(has(lines, "ERROR", "mate-count"))

    def test_name_mismatch(self):
        write_gz(self.p("S_R1.fastq.gz"), fastq_text(5)); write_gz(self.p("S_R2.fastq.gz"), fastq_text(5, 2, 2, names=[f"x{i}" for i in range(5)]))
        rc, lines, _ = audit("fastq", self.d)
        self.assertEqual(rc, 4); self.assertTrue(has(lines, "ERROR", "mate-names"))

    def test_quality_length_mismatch_and_truncation(self):
        write_gz(self.p("S_R1.fastq.gz"), fastq_text(5, qual_len_error=True)); write_gz(self.p("S_R2.fastq.gz"), fastq_text(5, 2, 2))
        self.assertTrue(has(audit("fastq", self.d)[1], "ERROR", "fastq-structure"))
        write_gz(self.p("T_R1.fastq.gz"), fastq_text(5) + "@broken\nACGT\n"); write_gz(self.p("T_R2.fastq.gz"), fastq_text(5, 2, 2))
        self.assertTrue(has(audit("fastq", self.d)[1], "ERROR", "fastq-structure"))

    def test_unpaired_warns_unless_single_end(self):
        write_gz(self.p("S_R1.fastq.gz"), fastq_text(5))
        rc, lines, _ = audit("fastq", self.d)
        self.assertTrue(has(lines, "WARN", "unpaired")); self.assertEqual(rc, 0)
        self.assertFalse(has(audit("fastq", self.d, "--single-end")[1], "WARN", "unpaired"))

    def test_index_reads_checked_against_r1(self):
        write_gz(self.p("S_R1.fastq.gz"), fastq_text(8)); write_gz(self.p("S_R2.fastq.gz"), fastq_text(8, 2, 2)); write_gz(self.p("S_I1.fastq.gz"), fastq_text(7, 3))
        self.assertTrue(has(audit("fastq", self.d)[1], "ERROR", "index-read-count"))

    def test_max_reads_cap_is_reported(self):
        write_gz(self.p("S_R1.fastq.gz"), fastq_text(50)); write_gz(self.p("S_R2.fastq.gz"), fastq_text(50, 2, 2))
        rc, lines, _ = audit("fastq", self.d, "--max-reads", "10")
        self.assertEqual(rc, 0); self.assertTrue(any("capped" in l[3] for l in lines if l[1] == "mate-count"))

    def test_no_fastq_is_error(self):
        write(self.p("x.txt"), "a")
        self.assertEqual(audit("fastq", self.d)[0], 4)


def make_10x(d, genes=5, cells=4, entries=None, field="integer", gene_ids=None, barcodes=None):
    gene_ids = gene_ids or [f"ENSG{i:011d}" for i in range(1, genes + 1)]
    barcodes = barcodes or [f"ACGTACGTACGTAC{i:02d}-1" for i in range(cells)]
    entries = entries if entries is not None else [(1, 1, 3), (2, 1, 1), (2, 2, 4), (3, 3, 2), (5, 4, 7)]
    write_gz(os.path.join(d, "matrix.mtx.gz"), mtx_text(genes, cells, entries, field))
    write_gz(os.path.join(d, "features.tsv.gz"), "".join(f"{g}\tG{i}\tGene Expression\n" for i, g in enumerate(gene_ids)))
    write_gz(os.path.join(d, "barcodes.tsv.gz"), "".join(b + "\n" for b in barcodes))


def make_parse(d, genes=5, cells=4, entries=None):
    entries = entries if entries is not None else [(1, 1, 3), (1, 2, 1), (2, 2, 4), (3, 3, 2), (4, 5, 7)]    # cells x genes
    write_gz(os.path.join(d, "count_matrix.mtx.gz"), mtx_text(cells, genes, entries))
    write_gz(os.path.join(d, "all_genes.csv.gz"), "gene_id,gene_name,genome\n" + "".join(f"ENSG{i:011d},G{i},hs\n" for i in range(1, genes + 1)))
    write_gz(os.path.join(d, "cell_metadata.csv.gz"), "bc_wells,bc1_well\n" + "".join(f"{i:02d}_01_01__s1,A{i}\n" for i in range(cells)))


class Matrix(Base):
    def test_clean_10x(self):
        make_10x(self.d)
        rc, lines, _ = audit("matrix", self.d)
        self.assertEqual(rc, 0, lines)
        self.assertTrue(has(lines, "OK", "orientation")); self.assertTrue(has(lines, "OK", "integer-counts"))

    def test_clean_parse_is_cells_by_genes(self):
        make_parse(self.d)
        rc, lines, _ = audit("matrix", self.d)
        self.assertEqual(rc, 0, lines); self.assertTrue(any(l[1] == "orientation" and "cells_x_genes" in l[3] and l[0] == "OK" for l in lines))

    def test_parse_matrix_in_10x_orientation_warns(self):
        make_parse(self.d, entries=[(1, 1, 3), (2, 2, 4), (3, 3, 2), (5, 4, 7)])
        write_gz(self.p("count_matrix.mtx.gz"), mtx_text(5, 4, [(1, 1, 3), (2, 2, 4), (3, 3, 2), (5, 4, 7)]))
        self.assertTrue(has(audit("matrix", self.d)[1], "WARN", "orientation"))

    def test_dimension_mismatch(self):
        make_10x(self.d)
        write_gz(self.p("matrix.mtx.gz"), mtx_text(6, 4, [(1, 1, 1)]))
        rc, lines, _ = audit("matrix", self.d)
        self.assertEqual(rc, 4); self.assertTrue(has(lines, "ERROR", "dimensions"))

    def test_square_matrix_is_ambiguous(self):
        make_10x(self.d, genes=4, cells=4, entries=[(1, 1, 1)])
        self.assertTrue(has(audit("matrix", self.d)[1], "WARN", "orientation-ambiguous"))

    def test_non_integer_values(self):
        make_10x(self.d, entries=[(1, 1, 0.5), (2, 2, 1.25)], field="real")
        rc, lines, _ = audit("matrix", self.d)
        self.assertEqual(rc, 4); self.assertTrue(has(lines, "ERROR", "non-integer"))
        rc2, lines2, _ = audit("matrix", self.d, "--expect", "any")
        self.assertEqual(rc2, 0); self.assertTrue(has(lines2, "INFO", "non-integer"))

    def test_negative_and_out_of_range(self):
        make_10x(self.d, entries=[(1, 1, -2), (9, 1, 1)])
        rc, lines, _ = audit("matrix", self.d)
        self.assertEqual(rc, 4); self.assertTrue(has(lines, "ERROR", "negative-values")); self.assertTrue(has(lines, "ERROR", "index-range"))

    def test_truncated_entries(self):
        make_10x(self.d)
        txt = mtx_text(5, 4, [(1, 1, 3), (2, 1, 1), (2, 2, 4), (3, 3, 2), (5, 4, 7)]).rsplit("\n", 3)[0] + "\n"
        write_gz(self.p("matrix.mtx.gz"), txt)
        self.assertTrue(has(audit("matrix", self.d)[1], "ERROR", "nnz"))

    def test_duplicate_ids_and_mixed_species(self):
        make_10x(self.d, gene_ids=["ENSG00000000001", "ENSG00000000001", "ENSMUSG00000000003", "ENSG00000000004", "ENSG00000000005"],
                 barcodes=["AAAAAAAAAAAAAAAA-1", "AAAAAAAAAAAAAAAA-1", "CCCCCCCCCCCCCCCC-1", "GGGGGGGGGGGGGGGG-1"])
        rc, lines, _ = audit("matrix", self.d)
        self.assertEqual(rc, 4)
        self.assertTrue(has(lines, "ERROR", "duplicate-gene-ids")); self.assertTrue(has(lines, "ERROR", "duplicate-cell-ids")); self.assertTrue(has(lines, "WARN", "mixed-species-ids"))

    def test_mostly_empty_cells_warn(self):
        make_10x(self.d, entries=[(1, 1, 3)])
        self.assertTrue(has(audit("matrix", self.d)[1], "WARN", "empty-cells"))

    def test_missing_files(self):
        self.assertEqual(audit("matrix", self.d)[0], 4)
        make_10x(self.d); os.remove(self.p("barcodes.tsv.gz"))
        self.assertTrue(has(audit("matrix", self.d)[1], "ERROR", "missing-annotation"))


class SampleSheet(Base):
    def sheet(self, text):
        write(self.p("sheet.csv"), text); return self.p("sheet.csv")

    def test_clean_sheet(self):
        write_gz(self.p("fq", "A_R1.fastq.gz"), "x"); write_gz(self.p("fq", "A_R2.fastq.gz"), "x")
        s = self.sheet("sample,fastq_1,fastq_2\nA,fq/A_R1.fastq.gz,fq/A_R2.fastq.gz\n")
        rc, lines, _ = audit("samplesheet", s, "--dir", self.d)
        self.assertEqual(rc, 0, lines)

    def test_missing_orphan_duplicate_and_spaces(self):
        write_gz(self.p("fq", "A_R1.fastq.gz"), "x"); write_gz(self.p("fq", "ORPHAN_R1.fastq.gz"), "x")
        s = self.sheet("sample,fastq_1,fastq_2\nA,fq/A_R1.fastq.gz,fq/A_R2.fastq.gz\nA,fq/A_R1.fastq.gz,\nB 1,fq/A_R1.fastq.gz,fq/A_R1.fastq.gz\n")
        rc, lines, _ = audit("samplesheet", s, "--dir", self.d)
        self.assertEqual(rc, 4)
        for sev, chk in [("ERROR", "missing-file"), ("ERROR", "duplicate-sample-id"), ("ERROR", "blank-file-entry"), ("WARN", "space-in-sample-id"), ("WARN", "orphan-file"), ("WARN", "file-reused")]:
            self.assertTrue(has(lines, sev, chk), (sev, chk, lines))

    def test_allow_repeats_for_multilane(self):
        write_gz(self.p("A1.fastq.gz"), "x"); write_gz(self.p("A2.fastq.gz"), "x")
        s = self.sheet("sample,fastq_1\nA,A1.fastq.gz\nA,A2.fastq.gz\n")
        self.assertEqual(audit("samplesheet", s, "--dir", self.d)[0], 4)
        self.assertEqual(audit("samplesheet", s, "--dir", self.d, "--allow-repeats")[0], 0)

    def test_tsv_sheet_and_missing_column(self):
        write_gz(self.p("a.fastq.gz"), "x")
        write(self.p("s.tsv"), "id\tfile\nA\ta.fastq.gz\n")
        self.assertEqual(audit("samplesheet", self.p("s.tsv"), "--dir", self.d)[0], 0)
        self.assertEqual(audit("samplesheet", self.p("s.tsv"), "--dir", self.d, "--id-col", "nope")[0], 4)


class Design(Base):
    def meta(self, text):
        write(self.p("m.tsv"), text); return self.p("m.tsv")

    def test_balanced_design_ok(self):
        rows = "sample\tcond\tbatch\n" + "".join(f"s{i}\t{'ctl' if i % 2 else 'trt'}\t{'b1' if i < 4 else 'b2'}\n" for i in range(8))
        rc, lines, _ = audit("design", self.meta(rows), "--factors", "cond,batch")
        self.assertEqual(rc, 0, lines)

    def test_perfect_confounding_is_error(self):
        rows = "sample\tcond\tbatch\n" + "".join(f"s{i}\t{'ctl' if i < 3 else 'trt'}\t{'b1' if i < 3 else 'b2'}\n" for i in range(6))
        rc, lines, _ = audit("design", self.meta(rows), "--factors", "cond,batch")
        self.assertEqual(rc, 4); self.assertTrue(has(lines, "ERROR", "confounded"))

    def test_single_replicate_warns(self):
        rows = "sample\tcond\ns1\tctl\ns2\ttrt\ns3\ttrt\n"
        rc, lines, _ = audit("design", self.meta(rows), "--factors", "cond")
        self.assertEqual(rc, 0); self.assertTrue(has(lines, "WARN", "replicates"))
        self.assertEqual(audit("--strict", "design", self.meta(rows), "--factors", "cond")[0], 4)

    def test_pseudoreplication_with_unit(self):
        rows = "cell\tcond\tdonor\n" + "".join(f"c{i}\tctl\td1\n" for i in range(20)) + "".join(f"t{i}\ttrt\t{'d2' if i < 10 else 'd3'}\n" for i in range(20))
        rc, lines, _ = audit("design", self.meta(rows), "--factors", "cond", "--unit", "donor")
        self.assertTrue(has(lines, "WARN", "pseudo-replication"))
        self.assertTrue(any(l[1] == "replicates" and l[0] == "OK" and "trt" in l[2] for l in lines))

    def test_nested_factor_warns(self):
        rows = "sample\tcond\tdonor\n" + "".join(f"s{i}\t{'ctl' if i < 4 else 'trt'}\td{i // 2}\n" for i in range(8))
        rc, lines, _ = audit("design", self.meta(rows), "--factors", "cond,donor")
        self.assertTrue(has(lines, "WARN", "nested"))

    def test_missing_column_and_values(self):
        self.assertEqual(audit("design", self.meta("a\tb\n1\t2\n"), "--factors", "zzz")[0], 4)
        rc, lines, _ = audit("design", self.meta("sample\tcond\ns1\t\ns2\tctl\ns3\tctl\n"), "--factors", "cond")
        self.assertTrue(has(lines, "WARN", "missing-value"))


class Cli(Base):
    def test_usage_errors(self):
        self.assertEqual(audit()[0], 2)
        self.assertEqual(audit("nope")[0], 2)

    def test_nonexistent_dir_is_internal_error_or_finding(self):
        rc, _, err = audit("matrix", self.p("missing"))
        self.assertIn(rc, (1, 4))


if __name__ == "__main__":
    unittest.main(verbosity=2)
