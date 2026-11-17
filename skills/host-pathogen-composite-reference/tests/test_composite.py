#!/usr/bin/env python3
"""Offline tests for host-pathogen-composite-reference scripts. Run: python3 tests/test_composite.py"""
import gzip
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = HERE.parent / "scripts"
FIX = HERE / "fixtures"


def py(script, *args):
    return subprocess.run([sys.executable, "-I", str(SC / script), *map(str, args)], capture_output=True, text=True)


def rand_seq(n, seed):
    r = random.Random(seed)
    return "".join(r.choice("ACGT") for _ in range(n))


def write_fa(path, recs, wrap=60, gz=False, trailing_newline=True):
    text = "".join(f">{n}\n" + "\n".join(s[i:i + wrap] for i in range(0, len(s), wrap)) + "\n" for n, s in recs.items())
    if not trailing_newline:
        text = text.rstrip("\n")
    with (gzip.open(path, "wt") if gz else open(path, "w")) as fh:
        fh.write(text)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)


class GoldenEquivalence(Tmp):
    """Output must equal what the original R implementation (GenomicRanges/rtracklayer) produced on the same GFF3."""
    CASES = {"ext5": ["--upstream-ext", "300", "--ext-for", "cds_only"],
             "ext3all": ["--upstream-ext", "0", "--downstream-ext", "200", "--ext-for", "all"]}

    def test_matches_r_reference_outputs(self):
        for name, extra in self.CASES.items():
            out = self.d / f"{name}.gtf"
            r = py("viral_quant_annotation.py", "--gff", FIX / "virus_linear.gff3", "--contig", "VIR1", "--strip-prefix", "HHV4_",
                   "--gtf-source", "ebv_quant", "--out-gtf", out, *extra)
            self.assertEqual(r.returncode, 0, r.stderr)
            exp = FIX / "expected"
            self.assertEqual(out.read_text(), (exp / f"{name}.gtf").read_text(), f"{name}: GTF differs from R output")
            self.assertEqual((self.d / f"{name}_genes.tsv").read_text(), (exp / f"{name}_genes.tsv").read_text(), f"{name}: gene table differs")
            self.assertEqual(sorted((self.d / f"{name}_overlaps.tsv").read_text().splitlines()),
                             sorted((exp / f"{name}_overlaps.tsv").read_text().splitlines()), f"{name}: overlaps differ")


class Annotation(Tmp):
    def run_circ(self, *extra):
        return py("viral_quant_annotation.py", "--gff", FIX / "virus_circular.gff3", "--contig", "CIRC1", "--strip-prefix", "C_", "--out-gtf", self.d / "c.gtf", *extra)

    def exons(self, gid):
        return [(int(x[3]), int(x[4])) for x in (ln.split("\t") for ln in (self.d / "c.gtf").read_text().splitlines())
                if x[2] == "exon" and f'gene_id "{gid}"' in x[8]]

    def test_origin_crossing_features_split(self):
        r = self.run_circ()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(self.exons("W1")), [(1, 100), (900, 1000)])
        self.assertEqual(sorted(self.exons("W2")), [(1, 40), (950, 1000)])   # written as start > end
        self.assertEqual(self.exons("W3"), [(10, 90)])                       # entirely beyond the end: shifted
        self.assertEqual(self.exons("N1"), [(310, 490)])
        wrapped = (self.d / "c_wrapped.tsv").read_text()
        self.assertIn("W1:exon", wrapped); self.assertIn("W2:CDS", wrapped); self.assertIn("W3:CDS", wrapped); self.assertNotIn("N1", wrapped)
        self.assertIn("crossed the contig origin", r.stderr)

    def test_minus_strand_transcript_order_for_split_blocks(self):
        self.run_circ()
        lines = [ln.split("\t") for ln in (self.d / "c.gtf").read_text().splitlines() if ln.split("\t")[2] == "exon" and 'gene_id "W2"' in ln]
        self.assertEqual([int(x[3]) for x in lines], [950, 1])  # '-' strand: highest block first

    def test_cap_mode_truncates_and_error_mode_stops(self):
        self.run_circ("--wrap", "cap")
        self.assertEqual(self.exons("W1"), [(900, 1000)])
        r = self.run_circ("--wrap", "error", "--overwrite")
        self.assertEqual(r.returncode, 1)
        self.assertIn("crosses the contig origin", r.stderr)

    def test_refuses_to_overwrite_and_duplicate_gene_ids(self):
        self.run_circ()
        self.assertEqual(self.run_circ().returncode, 1)
        dup = self.d / "dup.gff3"
        dup.write_text("##gff-version 3\n##sequence-region X 1 500\n"
                       "X\tr\tgene\t1\t100\t.\t+\t.\tID=g1;Name=A;locus_tag=L1\nX\tr\tgene\t200\t300\t.\t+\t.\tID=g2;Name=B;locus_tag=L1\n")
        r = py("viral_quant_annotation.py", "--gff", dup, "--contig", "X", "--out-gtf", self.d / "d.gtf")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not unique", r.stderr)

    def test_coordinates_outside_contig_without_wrap_pattern_fail(self):
        bad = self.d / "bad.gff3"
        bad.write_text("##gff-version 3\n##sequence-region X 1 500\nX\tr\tgene\t0\t100\t.\t+\t.\tID=g1;Name=A;locus_tag=L1\n")
        r = py("viral_quant_annotation.py", "--gff", bad, "--contig", "X", "--out-gtf", self.d / "b.gtf")
        self.assertEqual(r.returncode, 1)
        self.assertIn("outside contig length", r.stderr)

    def test_contig_length_from_fasta(self):
        write_fa(self.d / "v.fa", {"VIR1": rand_seq(3000, 1)})
        r = py("viral_quant_annotation.py", "--gff", FIX / "virus_linear.gff3", "--contig", "VIR1", "--fasta", self.d / "v.fa", "--out-gtf", self.d / "v.gtf")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("length 3000", r.stderr)


class Composite(Tmp):
    def make_inputs(self, host_trailing_newline=True, virus_contig="VIR1"):
        write_fa(self.d / "host.fa.gz", {"chr1": rand_seq(1200, 2), "chr2": rand_seq(800, 3)}, gz=True, trailing_newline=host_trailing_newline)
        write_fa(self.d / "virus.fa", {virus_contig: rand_seq(3000, 4)})
        with gzip.open(self.d / "host.gtf.gz", "wt") as fh:
            fh.write('#!genome-build test\n'
                     'chr1\tHAVANA\tgene\t100\t900\t.\t+\t.\tgene_id "H1"; gene_name "H1";\n'
                     'chr1\tHAVANA\ttranscript\t100\t900\t.\t+\t.\tgene_id "H1"; transcript_id "H1.1";\n'
                     'chr1\tHAVANA\texon\t100\t900\t.\t+\t.\tgene_id "H1"; transcript_id "H1.1";\n')
        r = py("viral_quant_annotation.py", "--gff", FIX / "virus_linear.gff3", "--contig", "VIR1", "--strip-prefix", "HHV4_", "--out-gtf", self.d / "virus.gtf")
        self.assertEqual(r.returncode, 0, r.stderr)

    def build(self):
        return py("composite_ref.py", "build", "--host-fasta", self.d / "host.fa.gz", "--host-gtf", self.d / "host.gtf.gz",
                  "--virus-fasta", self.d / "virus.fa", "--virus-gtf", self.d / "virus.gtf", "--out-fasta", self.d / "c.fa", "--out-gtf", self.d / "c.gtf")

    def test_build_and_check_ok(self):
        self.make_inputs()
        self.assertEqual(self.build().returncode, 0)
        r = py("composite_ref.py", "check", "--fasta", self.d / "c.fa", "--gtf", self.d / "c.gtf", "--pathogen-contig", "VIR1", "--strict")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)
        contigs = (self.d / "c.fa.contigs.tsv").read_text().splitlines()
        self.assertEqual([x.split("\t")[0] for x in contigs[1:]], ["chr1", "chr2", "VIR1"])
        self.assertEqual(contigs[3].split("\t")[1:], ["3000", "pathogen"])

    def test_host_fasta_without_trailing_newline_does_not_swallow_the_virus_header(self):
        self.make_inputs(host_trailing_newline=False)
        self.assertEqual(self.build().returncode, 0)
        names = [ln.split("\t")[0] for ln in (self.d / "c.fa.contigs.tsv").read_text().splitlines()[1:]]
        self.assertEqual(names, ["chr1", "chr2", "VIR1"])
        with open(self.d / "c.fa") as fh:
            self.assertEqual(sum(1 for ln in fh if ln.startswith(">")), 3)

    def test_contig_name_collision_is_refused(self):
        self.make_inputs(virus_contig="chr2")
        r = self.build()
        self.assertEqual(r.returncode, 1)
        self.assertIn("duplicate contig name", r.stderr)

    def test_check_finds_the_classic_problems(self):
        self.make_inputs()
        self.build()
        gtf = (self.d / "c.gtf").read_text()
        bad = gtf + ('VIR1\tx\texon\t2900\t3100\t.\t+\t.\tgene_id "Z"; transcript_id "Z";\n'          # beyond contig end
                     'NOPE\tx\texon\t1\t10\t.\t+\t.\tgene_id "Q"; transcript_id "Q";\n'               # contig not in FASTA
                     'VIR1\tx\texon\t10\t20\t.\t+\t.\tgene_id "NT";\n')                              # no transcript_id
        (self.d / "bad.gtf").write_text(bad)
        r = py("composite_ref.py", "check", "--fasta", self.d / "c.fa", "--gtf", self.d / "bad.gtf")
        self.assertEqual(r.returncode, 1)
        for s in ("coordinates outside contig", "GTF contig absent from FASTA", "without gene_id or transcript_id"):
            self.assertIn(s, r.stdout)

    def test_check_warns_about_genes_without_exon_rows(self):
        self.make_inputs()
        self.build()
        gtf = [ln for ln in (self.d / "c.gtf").read_text().splitlines() if "\texon\t" not in ln or "VIR1" not in ln]  # drop all viral exon rows
        (self.d / "noexon.gtf").write_text("\n".join(gtf) + "\n")
        r = py("composite_ref.py", "check", "--fasta", self.d / "c.fa", "--gtf", self.d / "noexon.gtf", "--pathogen-contig", "VIR1")
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARNING: genes with a gene row but no exon rows", r.stdout)
        self.assertEqual(py("composite_ref.py", "check", "--fasta", self.d / "c.fa", "--gtf", self.d / "noexon.gtf", "--pathogen-contig", "VIR1", "--strict").returncode, 1)

    def test_star_params_follow_total_genome_length(self):
        import json
        for n, expect in ((3_100_000_000, 14), (3_100_171_823, 14), (171_823, 7), (23_000, 6), (1_000_000, 8)):
            r = py("composite_ref.py", "star-params", "--genome-length", n, "--json")
            self.assertEqual(json.loads(r.stdout)["genomeSAindexNbases"], expect, n)
        r = py("composite_ref.py", "star-params", "--genome-length", 1000000, "--read-length", 90)
        self.assertIn("--sjdbOverhang 89", r.stdout)


class Preflight(Tmp):
    def fastq(self, path, barcodes, tail="A" * 10):
        with open(path, "w") as fh:
            for i, b in enumerate(barcodes):
                fh.write(f"@r{i}\n{b}{tail}\n+\n{'I' * (len(b) + len(tail))}\n")

    def test_hit_rate_and_exit_codes(self):
        wl_a = [rand_seq(16, 100 + i) for i in range(500)]
        wl_b = [rand_seq(16, 9000 + i) for i in range(500)]
        (self.d / "a.txt").write_text("\n".join(wl_a))   # no trailing newline, like real whitelists
        (self.d / "b.txt").write_text("\n".join(wl_b))
        self.fastq(self.d / "r1.fastq", wl_a[:400])
        r = py("whitelist_preflight.py", "--r1", self.d / "r1.fastq", "--whitelist", self.d / "a.txt", self.d / "b.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("exact_hit=1.0000", r.stdout)
        self.assertIn("best match", r.stdout)
        r = py("whitelist_preflight.py", "--r1", self.d / "r1.fastq", "--whitelist", self.d / "b.txt")
        self.assertEqual(r.returncode, 3)
        self.assertIn("wrong chemistry", r.stderr)

    def test_reverse_complement_diagnostic(self):
        wl = [rand_seq(16, 7 + i) for i in range(200)]
        (self.d / "w.txt").write_text("\n".join(wl))
        rc = [w.translate(str.maketrans("ACGT", "TGCA"))[::-1] for w in wl]
        self.fastq(self.d / "r1.fastq", rc)
        r = py("whitelist_preflight.py", "--r1", self.d / "r1.fastq", "--whitelist", self.d / "w.txt")
        self.assertEqual(r.returncode, 3)
        self.assertIn("revcomp_hit=1.0000", r.stdout)


@unittest.skipUnless(shutil.which("STAR"), "STAR not installed")
class StarEndToEnd(Tmp):
    """Index a tiny host+virus composite built by these scripts and count reads per gene."""

    def test_cds_only_viral_gene_is_counted_only_after_annotation_rescue(self):
        host = {"chr1": rand_seq(12000, 11), "chr2": rand_seq(8000, 12)}
        vir = rand_seq(3000, 13)
        write_fa(self.d / "host.fa", host)
        write_fa(self.d / "virus.fa", {"VIR1": vir})
        (self.d / "host.gtf").write_text('chr1\tx\texon\t2000\t2500\t.\t+\t.\tgene_id "HG1"; transcript_id "HG1.1"; gene_name "HG1";\n')
        self.assertEqual(py("viral_quant_annotation.py", "--gff", FIX / "virus_linear.gff3", "--contig", "VIR1", "--strip-prefix", "HHV4_",
                            "--out-gtf", self.d / "virus.gtf").returncode, 0)
        # naive conversion, as a straightforward GFF3 -> GTF script does it: keep gene/mRNA/exon/CDS rows, gene_id from the 'gene' attribute
        naive = []
        for ln in (FIX / "virus_linear.gff3").read_text().splitlines():
            c = ln.split("\t")
            if len(c) < 9 or c[2] not in ("gene", "mRNA", "exon", "CDS"):
                continue
            at = dict(kv.split("=", 1) for kv in c[8].split(";") if "=" in kv)
            gid = at.get("gene", at["ID"])
            naive.append("\t".join(c[:2] + ["transcript" if c[2] == "mRNA" else c[2]] + c[3:8] + [f'gene_id "{gid}"; transcript_id "{at.get("ID", gid)}";']))
        (self.d / "virus_naive.gtf").write_text("\n".join(naive) + "\n")
        counts = {}
        for tag, vg in (("rescued", "virus.gtf"), ("naive", "virus_naive.gtf")):
            cd = self.d / tag
            cd.mkdir()
            self.assertEqual(py("composite_ref.py", "build", "--host-fasta", self.d / "host.fa", "--host-gtf", self.d / "host.gtf", "--virus-fasta", self.d / "virus.fa",
                                "--virus-gtf", self.d / vg, "--out-fasta", cd / "c.fa", "--out-gtf", cd / "c.gtf").returncode, 0)
            sa = int(__import__("json").loads(py("composite_ref.py", "star-params", "--fasta", cd / "c.fa", "--json").stdout)["genomeSAindexNbases"])
            self.assertEqual(sa, 6)
            idx = cd / "idx"
            r = subprocess.run(["STAR", "--runMode", "genomeGenerate", "--runThreadN", "2", "--genomeDir", str(idx), "--genomeFastaFiles", str(cd / "c.fa"),
                                "--sjdbGTFfile", str(cd / "c.gtf"), "--sjdbOverhang", "49", "--genomeSAindexNbases", str(sa), "--outFileNamePrefix", str(cd / "gen_")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            # reads: 100 from host gene HG1 exon, 100 from viral gene GB (CDS-only in the GFF3, 520..880)
            reads = [host["chr1"][2100 - 1 + 3 * i:2100 - 1 + 3 * i + 50] for i in range(100)] + [vir[600 - 1 + 2 * i:600 - 1 + 2 * i + 50] for i in range(100)]
            (cd / "r.fq").write_text("".join(f"@r{i}\n{s}\n+\n{'I' * 50}\n" for i, s in enumerate(reads)))
            r = subprocess.run(["STAR", "--runThreadN", "2", "--genomeDir", str(idx), "--readFilesIn", str(cd / "r.fq"), "--quantMode", "GeneCounts",
                                "--outFileNamePrefix", str(cd / "al_")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            rows = [ln.split("\t") for ln in (cd / "al_ReadsPerGene.out.tab").read_text().splitlines()]
            counts[tag] = {x[0]: int(x[1]) for x in rows if not x[0].startswith("N_")}
            chk = py("composite_ref.py", "check", "--fasta", cd / "c.fa", "--gtf", cd / "c.gtf", "--pathogen-contig", "VIR1")
            counts[tag + "_check"] = chk.stdout
        self.assertGreaterEqual(counts["rescued"]["HG1"], 95)
        self.assertGreaterEqual(counts["rescued"]["GB"], 95)          # CDS-only gene is quantified
        self.assertNotIn("GB", counts["naive"])                       # without exon rows STAR does not even list it
        self.assertIn("no exon rows", counts["naive_check"])           # ... and the check says so before the index is built
        self.assertNotIn("WARNING", counts["rescued_check"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
