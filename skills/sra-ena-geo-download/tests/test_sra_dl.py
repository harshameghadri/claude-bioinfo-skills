#!/usr/bin/env python3
"""Offline tests for scripts/sra_dl.py. No network, no model. Run: python3 tests/test_sra_dl.py"""
import hashlib
import http.server
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "scripts" / "sra_dl.py"
FIX = HERE / "fixtures"
ENV = dict(os.environ, SRA_DL_RETRY_SLEEP="0")


def run(*args, env=None, cwd=None):
    return subprocess.run([sys.executable, "-I", str(TOOL), *map(str, args)], capture_output=True, text=True,
                          env=env or ENV, cwd=cwd)


def rows(path):
    lines = Path(path).read_text().splitlines()
    hdr = lines[0].split("\t")
    return [dict(zip(hdr, ln.split("\t"))) for ln in lines[1:]]


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)


class LookupEna(Tmp):
    def test_paired_plus_unpaired_all_files_kept(self):
        r = run("lookup-ena", "--runs", "SRR9000004", "--offline-dir", FIX, "--files-tsv", self.d / "f.tsv", "--unresolved-tsv", self.d / "u.tsv")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = rows(self.d / "f.tsv")
        self.assertEqual([x["filename"] for x in got], ["SRR9000004_1.fastq.gz", "SRR9000004_2.fastq.gz", "SRR9000004.fastq.gz"])
        self.assertTrue(got[0]["url"].startswith("http://ftp.sra.ebi.ac.uk/"))
        self.assertEqual(got[1]["md5"], "2" * 32)
        self.assertEqual(got[2]["bytes"], "300")

    def test_https_scheme(self):
        run("lookup-ena", "--runs", "SRR9000004", "--scheme", "https", "--offline-dir", FIX, "--files-tsv", self.d / "f.tsv", "--unresolved-tsv", self.d / "u.tsv")
        self.assertTrue(rows(self.d / "f.tsv")[0]["url"].startswith("https://"))

    def test_empty_fastq_ftp_is_reported_not_silently_skipped(self):
        r = run("lookup-ena", "--runs", "SRR9000002", "--offline-dir", FIX, "--files-tsv", self.d / "f.tsv", "--unresolved-tsv", self.d / "u.tsv")
        self.assertEqual(r.returncode, 3)
        self.assertIn("empty_fastq_ftp", (self.d / "u.tsv").read_text())
        self.assertEqual(rows(self.d / "f.tsv"), [])

    def test_unknown_run_and_html_error_page_are_unresolved(self):
        r = run("lookup-ena", "--runs", "SRR9000003", "SRR9000007", "SRR9999999", "--offline-dir", FIX,
                "--files-tsv", self.d / "f.tsv", "--unresolved-tsv", self.d / "u.tsv")
        self.assertEqual(r.returncode, 3)
        u = (self.d / "u.tsv").read_text()
        self.assertIn("not_in_ena", u)
        self.assertEqual(u.count("lookup_failed"), 2)  # html page + missing fixture

    def test_project_accession_expands_to_runs_and_md5_mismatch_is_flagged(self):
        r = run("lookup-ena", "--runs", "PRJNA900001", "--offline-dir", FIX, "--files-tsv", self.d / "f.tsv", "--unresolved-tsv", self.d / "u.tsv")
        self.assertEqual(r.returncode, 3)  # second run has no FASTQ
        got = rows(self.d / "f.tsv")
        self.assertEqual({x["run"] for x in got}, {"SRR9000005"})
        self.assertTrue(all(x["md5"] == "" and "md5_unavailable" in x["note"] for x in got))  # 1 md5 for 2 files: refuse to guess the mapping

    def test_manifest_dest_and_traversal_guard(self):
        m = self.d / "m.tsv"
        m.write_text("srr\tdest\tother\nSRR9000004\tdonorA/gex\tx\n")
        run("lookup-ena", "--manifest", m, "--out-dir", self.d / "out", "--offline-dir", FIX, "--files-tsv", self.d / "f.tsv", "--unresolved-tsv", self.d / "u.tsv")
        self.assertTrue(rows(self.d / "f.tsv")[0]["dest_dir"].endswith("out/donorA/gex"))
        m.write_text("run\tdest\nSRR9000004\t../escape\n")
        r = run("lookup-ena", "--manifest", m, "--offline-dir", FIX, "--files-tsv", self.d / "f.tsv")
        self.assertEqual(r.returncode, 2)

    def test_bad_accession_is_a_usage_error(self):
        self.assertEqual(run("lookup-ena", "--runs", "SRR1;rm -rf", "--offline-dir", FIX).returncode, 2)
        self.assertEqual(run("lookup-ena").returncode, 2)

    def test_append_keeps_single_header(self):
        a = ["--offline-dir", FIX, "--files-tsv", self.d / "f.tsv", "--unresolved-tsv", self.d / "u.tsv"]
        run("lookup-ena", "--runs", "SRR9000004", *a)
        run("lookup-ena", "--runs", "PRJNA900001", "--append", *a)
        text = (self.d / "f.tsv").read_text()
        self.assertEqual(text.count("run\tdest_dir"), 1)
        self.assertEqual(len(rows(self.d / "f.tsv")), 5)


class LookupSdl(Tmp):
    def go(self, acc, *extra):
        r = run("lookup-sdl", "--runs", acc, "--offline-dir", FIX, "--files-tsv", self.d / "f.tsv", "--unresolved-tsv", self.d / "u.tsv", *extra)
        return r, (rows(self.d / "f.tsv") if (self.d / "f.tsv").exists() else [])

    def test_index_read_is_not_mistaken_for_mate1(self):
        r, got = self.go("SRR9000010")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({x["filename"] for x in got}, {"SRR9000010_1.fastq.gz", "SRR9000010_2.fastq.gz", "SRR9000010_I1.fastq.gz"})
        r1 = next(x for x in got if x["filename"].endswith("_1.fastq.gz"))
        self.assertIn("_R1_", r1["url"])

    def test_multilane_keeps_original_names(self):
        r, got = self.go("SRR9000011")
        self.assertEqual(len(got), 4)
        self.assertTrue(all(x["filename"].startswith("S1_L00") and "kept_original_names" in x["note"] for x in got))

    def test_unrecognised_roles_keep_original_names(self):
        _, got = self.go("SRR9000014")
        self.assertEqual({x["filename"] for x in got}, {"reads_a.fastq.gz", "reads_b.fastq.gz"})

    def test_sra_kind(self):
        r, got = self.go("SRR9000012", "--kind", "sra")
        self.assertEqual(got[0]["filename"], "SRR9000012.sra")
        self.assertEqual(got[0]["md5"], "b" * 32)
        self.assertEqual(got[0]["bytes"], "5000")

    def test_missing_kind_is_unresolved(self):
        r, _ = self.go("SRR9000013")  # only an sra object exists, source requested
        self.assertEqual(r.returncode, 3)


class GeoSuppl(Tmp):
    def test_listing_excludes_parent_and_sort_links(self):
        r = run("geo-suppl", "--series", "GSE900001", "--sample", "GSM900001", "--offline-dir", FIX,
                "--files-tsv", self.d / "f.tsv", "--unresolved-tsv", self.d / "u.tsv", "--out-dir", self.d / "geo")
        self.assertEqual(r.returncode, 3)  # the sample has no files
        got = rows(self.d / "f.tsv")
        self.assertEqual([x["filename"] for x in got], ["GSE900001_RAW.tar", "GSE900001_counts.csv.gz"])
        self.assertEqual(got[0]["url"], "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE900nnn/GSE900001/suppl/GSE900001_RAW.tar")
        self.assertIn("GSM900001", (self.d / "u.tsv").read_text())


class Resolve(Tmp):
    def test_runinfo_to_manifest_with_dest_template(self):
        r = run("resolve", "--accessions", "GSM900100", "--offline-dir", FIX, "--out", self.d / "m.tsv",
                "--dest-template", "{SampleName}/{LibraryStrategy}")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = rows(self.d / "m.tsv")
        self.assertEqual([x["run"] for x in got], ["SRR9300001", "SRR9300002"])
        self.assertEqual(got[0]["dest"], "Donor_1_rep_A/RNA-Seq")  # unsafe characters replaced
        self.assertEqual(got[1]["spots"], "2000")

    def test_unknown_accession_is_unresolved(self):
        r = run("resolve", "--accessions", "GSM900100", "SRP000000", "--offline-dir", FIX, "--out", self.d / "m.tsv",
                "--unresolved-tsv", self.d / "u.tsv")
        self.assertEqual(r.returncode, 3)
        self.assertIn("SRP000000", (self.d / "u.tsv").read_text())

    def test_manifest_feeds_lookup_and_jobs_spot_check(self):
        run("resolve", "--accessions", "SRP900100", "--offline-dir", FIX, "--out", self.d / "m.tsv")
        r = run("jobs", "--kind", "sra-file", "--manifest", self.d / "m.tsv", "--job-dir", self.d / "jobs", "--out-dir", self.d / "o", "--runner", "print")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("EXPECT_SPOTS=1000", (self.d / "jobs" / "SRR9300001.sh").read_text())


class FallbackChain(Tmp):
    def test_unresolved_file_feeds_the_next_rung_directly(self):
        off = self.d / "off"
        shutil.copytree(FIX, off)
        shutil.copy(FIX / "SRR9000010.json", off / "SRR9000002.json")  # SDL has the run that ENA lacks
        a = ["--offline-dir", off, "--files-tsv", self.d / "f.tsv"]
        r = run("lookup-ena", "--runs", "SRR9000004", "SRR9000002", *a, "--unresolved-tsv", self.d / "u.tsv")
        self.assertEqual(r.returncode, 3)
        r = run("lookup-sdl", "--manifest", self.d / "u.tsv", "--append", *a, "--unresolved-tsv", self.d / "u2.tsv")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({x["source"] for x in rows(self.d / "f.tsv")}, {"ena", "sdl-source"})


class QuietServer(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@unittest.skipUnless(shutil.which("aria2c"), "aria2c not installed")
class FetchVerifyEndToEnd(Tmp):
    """Real aria2c downloads from a local HTTP server, with md5 verification, resume and corruption detection."""

    def setUp(self):
        super().setUp()
        self.www = self.d / "www"
        self.www.mkdir()
        self.payload = {n: os.urandom(50_000 + i) for i, n in enumerate(["SRR9100001_1.fastq.gz", "SRR9100001_2.fastq.gz"])}
        for n, b in self.payload.items():
            (self.www / n).write_bytes(b)
        handler = lambda *a, **k: QuietServer(*a, directory=str(self.www), **k)
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        port = self.srv.server_address[1]
        self.off = self.d / "offline"
        self.off.mkdir()
        urls = ";".join(f"127.0.0.1:{port}/{n}" for n in self.payload)
        md5s = ";".join(hashlib.md5(b).hexdigest() for b in self.payload.values())
        sizes = ";".join(str(len(b)) for b in self.payload.values())
        (self.off / "SRR9100001.tsv").write_text(f"run_accession\tfastq_ftp\tfastq_md5\tfastq_bytes\nSRR9100001\t{urls}\t{md5s}\t{sizes}\n")
        self.ft = self.d / "files.tsv"
        r = run("lookup-ena", "--runs", "SRR9100001", "--offline-dir", self.off, "--out-dir", self.d / "fastq", "--files-tsv", self.ft,
                "--unresolved-tsv", self.d / "u.tsv")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_print_runner_creates_nothing(self):
        r = run("fetch", "--files-tsv", self.ft, "--runner", "print", "--aria2c", "aria2c-not-installed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("--checksum=md5="), 2)
        self.assertIn("--auto-file-renaming=false", r.stdout)
        self.assertFalse((self.d / "fastq").exists())

    def test_download_verify_resume_and_corruption(self):
        r = run("fetch", "--files-tsv", self.ft, "--runner", "direct", "--jobs", "2", "--connections", "4", "--split", "4")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.d / "fastq" / "."
        for n, b in self.payload.items():
            self.assertEqual((out / n).read_bytes(), b)
        v = run("verify", "--files-tsv", self.ft, "--report-dir", self.d / "v", "--write-sha256")
        self.assertEqual(v.returncode, 0, v.stderr)
        self.assertTrue((out / "SHA256SUMS").is_file())
        again = run("fetch", "--files-tsv", self.ft, "--runner", "direct")
        self.assertIn("already complete: 2", again.stderr)
        # corrupt one byte, same size: size check passes, md5 must catch it
        victim = out / "SRR9100001_2.fastq.gz"
        data = bytearray(victim.read_bytes())
        data[10] ^= 0xFF
        victim.write_bytes(bytes(data))
        v = run("verify", "--files-tsv", self.ft, "--report-dir", self.d / "v")
        self.assertEqual(v.returncode, 4)
        self.assertIn("SRR9100001_2.fastq.gz", (self.d / "v" / "corrupt_files.txt").read_text())
        self.assertEqual(run("verify", "--files-tsv", self.ft, "--report-dir", self.d / "v", "--no-md5").returncode, 0)  # size-only misses it
        # truncated + missing
        victim.write_bytes(b"short")
        (out / "SRR9100001_1.fastq.gz").unlink()
        v = run("verify", "--files-tsv", self.ft, "--report-dir", self.d / "v")
        self.assertEqual(v.returncode, 4)
        self.assertIn("SRR9100001_1.fastq.gz", (self.d / "v" / "missing_files.txt").read_text())
        status = {x["path"].split("/")[-1]: x["status"] for x in rows(self.d / "v" / "verify_report.tsv")}
        self.assertEqual(status["SRR9100001_2.fastq.gz"], "size_mismatch")

    def test_sidecar_means_incomplete(self):
        run("fetch", "--files-tsv", self.ft, "--runner", "direct")
        side = self.d / "fastq" / "SRR9100001_1.fastq.gz.aria2"
        side.write_bytes(b"x")
        again = run("fetch", "--files-tsv", self.ft, "--runner", "print")
        self.assertIn("already complete: 1", again.stderr)
        v = run("verify", "--files-tsv", self.ft, "--report-dir", self.d / "v")
        self.assertEqual(v.returncode, 4)

    def test_wrong_md5_makes_aria2c_fail_and_tool_exit_nonzero(self):
        t = self.ft.read_text().replace(hashlib.md5(self.payload["SRR9100001_1.fastq.gz"]).hexdigest(), "0" * 32)
        self.ft.write_text(t)
        r = run("fetch", "--files-tsv", self.ft, "--runner", "direct", "--connections", "2", "--split", "2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED", r.stderr)


class PueueRunner(Tmp):
    def stub(self):
        bindir = self.d / "bin"
        bindir.mkdir()
        log = self.d / "pueue.log"
        s = bindir / "pueue"
        s.write_text(f'#!/usr/bin/env bash\nprintf \'%s\\0\' "$@" >> {log}; printf \'\\n--\\n\' >> {log}\n'
                     '[[ " $* " == *" -p "* ]] && echo 42 || true\nexit 0\n')
        s.chmod(0o755)
        return dict(ENV, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}"), log

    def files(self, url):
        ft = self.d / "files.tsv"
        ft.write_text("run\tdest_dir\tfilename\turl\tmd5\tbytes\tsource\tnote\n"
                      f"R1\t{self.d}/out\ta.fastq.gz\t{url}\t{'a' * 32}\t10\tena\t\n"
                      f"R2\t{self.d}/out\tb.fastq.gz\t{url}\t\t10\tena\t\n")
        return ft

    def test_argv_passed_through_without_bash_c_and_gate_chains_jobs(self):
        env, log = self.stub()
        r = run("fetch", "--files-tsv", self.files("http://h/x.gz"), "--runner", "pueue", "--gate", "--pueue-group", "g1", "--aria2c", "aria2c", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = [c.strip("\0").split("\0") for c in log.read_text().split("\n--\n") if c.strip()]
        adds = [c for c in calls if c[0] == "add"]
        self.assertEqual(len(adds), 2)
        self.assertIn("-p", adds[0]); self.assertNotIn("--after", adds[0])
        self.assertEqual(adds[1][adds[1].index("--after") + 1], "42")
        for a in adds:
            tail = a[a.index("--") + 1:]
            self.assertEqual(tail[0], "aria2c"); self.assertNotIn("bash", tail[:2])
        self.assertIn("--checksum=md5=" + "a" * 32, adds[0])

    def test_unsafe_argument_is_refused(self):
        env, _ = self.stub()
        r = run("fetch", "--files-tsv", self.files("http://h/x.gz?a=1&b=2"), "--runner", "pueue", env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not safe to pass through pueue", r.stderr)

    def test_unknown_runner_is_rejected_by_the_parser(self):
        self.assertEqual(run("fetch", "--runner", "queue").returncode, 2)


class Jobs(Tmp):
    def fake_sra_bin(self, spots="1,000"):
        b = self.d / "sra_bin"
        b.mkdir()
        (b / "prefetch").write_text('#!/usr/bin/env bash\nrun=$1; shift; out=""; while [[ $# -gt 0 ]]; do [[ $1 == --output-directory ]] && out=$2; shift; done\nmkdir -p "$out"; echo sra > "$out/$run"\n')
        (b / "fasterq-dump").write_text(f'#!/usr/bin/env bash\nsrc=$1; shift; out=""; while [[ $# -gt 0 ]]; do [[ $1 == --outdir ]] && out=$2; shift; done\n'
                                        f'run=$(basename "$src" .sra); mkdir -p "$out"; printf "@r\\nACGT\\n+\\nIIII\\n" > "$out/${{run}}_1.fastq"; printf "@r\\nACGT\\n+\\nIIII\\n" > "$out/${{run}}_2.fastq"\n'
                                        f'echo "spots read      : {spots}"\n')
        for p in b.iterdir():
            p.chmod(0o755)
        return b

    def gen(self, kind, *extra):
        return run("jobs", "--kind", kind, "--runs", "SRR9200001", "--out-dir", self.d / "fastq", "--job-dir", self.d / "jobs",
                   "--sra-bin", self.d / "sra_bin", "--cache-root", self.d / "cache", "--pigz", "gzip", "--runner", "print", *extra)

    def test_prefetch_job_runs_and_cleans_cache(self):
        self.fake_sra_bin()
        r = self.gen("prefetch", "--include-technical")
        self.assertEqual(r.returncode, 0, r.stderr)
        job = self.d / "jobs" / "SRR9200001.sh"
        self.assertIn("--include-technical", job.read_text())
        if shutil.which("shellcheck"):
            sc = subprocess.run(["shellcheck", "-S", "warning", str(job)], capture_output=True, text=True)
            self.assertEqual(sc.returncode, 0, sc.stdout)
        self.assertEqual(subprocess.run(["bash", str(job)], capture_output=True, text=True).returncode, 0)
        self.assertTrue((self.d / "fastq" / "SRR9200001_1.fastq.gz").is_file())
        self.assertTrue((self.d / "fastq" / "SRR9200001_2.fastq.gz").is_file())
        self.assertFalse((self.d / "cache" / "SRR9200001").exists())

    def test_sra_file_job_spot_check_pass_and_fail(self):
        self.fake_sra_bin(spots="1,000")
        (self.d / "fastq").mkdir()
        (self.d / "fastq" / "SRR9200001.sra").write_text("x")
        m = self.d / "m.tsv"
        m.write_text("run\tspots\nSRR9200001\t1000\n")
        self.assertEqual(self.gen("sra-file", "--manifest", m).returncode, 0)
        ok = subprocess.run(["bash", str(self.d / "jobs" / "SRR9200001.sh")], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        man = (self.d / "fastq" / "SRR9200001.download_manifest.tsv").read_text().splitlines()
        self.assertEqual(len(man), 3)
        self.assertRegex(man[1], r"^SRR9200001_1\.fastq\.gz\t[0-9a-f]{64}$")
        self.assertFalse((self.d / "fastq" / ".work_SRR9200001").exists())
        # mismatch
        m.write_text("run\tspots\nSRR9200001\t999\n")
        self.gen("sra-file", "--manifest", m)
        bad = subprocess.run(["bash", str(self.d / "jobs" / "SRR9200001.sh")], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("spot mismatch", bad.stderr)

    def test_no_spot_count_warns(self):
        self.fake_sra_bin()
        (self.d / "fastq").mkdir()
        (self.d / "fastq" / "SRR9200001.sra").write_text("x")
        self.gen("sra-file")
        r = subprocess.run(["bash", str(self.d / "jobs" / "SRR9200001.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("spot check skipped", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
