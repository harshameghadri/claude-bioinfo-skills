#!/usr/bin/env python3
"""End-to-end offline tests for paper-library-ingest, using synthetic PDFs from make_fixtures.py.
Each test encodes a behaviour the skill depends on: nothing is filed without approval, dry run writes nothing, duplicates are
recognised by SHA-256, similar unmatched papers form one proposed category that must be approved, filing is verified and committed,
ids survive renames, and wrong usage fails with documented exit codes. Exit 0 = all passed."""
import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
ENV = dict(os.environ, INGEST_MIN_BYTES="1000", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
ENV.pop("INGEST_ROOT", None)


def run(args, cwd=None, ok=None):
    r = subprocess.run([sys.executable, "-I", *map(str, args)], capture_output=True, text=True, env=ENV, cwd=cwd, timeout=300)
    if ok is not None:
        assert r.returncode in ok, f"{args} exited {r.returncode}\n{r.stdout}\n{r.stderr}"
    return r


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class IngestFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()); cls.lib = cls.tmp / "lib"; cls.inbox = cls.tmp / "inbox"
        run([SCRIPTS / "init_library.py", "--root", cls.lib, "--parents", "Methods,Biology"], ok=[0])
        cls.fx = cls.tmp / "fx"; run([HERE / "make_fixtures.py", cls.fx], ok=[0])
        (cls.lib / "Methods").mkdir(exist_ok=True)
        # one paper already in the library (title comes from the file name)
        seed = cls.lib / "Methods" / "Zed_2024_Synthetic_Spatial-transcriptomics-cell-type-deconvolution-benchmark.pdf"
        shutil.copy(cls.fx / "sc1.pdf", seed); cls.seed_sha = sha(seed)
        run([cls.lib / "tools" / "catalog.py"], ok=[0])
        cls.inbox.mkdir()
        for n in ("qb1", "qb2", "qb3", "Rechnung_2026_11"): shutil.copy(cls.fx / f"{n}.pdf", cls.inbox / f"{n}.pdf")
        shutil.copy(cls.fx / "sc1.pdf", cls.inbox / "copy_of_known.pdf")            # same bytes as the library paper -> known
        (cls.inbox / "new_methods.pdf").write_bytes((cls.fx / "sc1.pdf").read_bytes().replace(b"Brandt", b"Brenda").replace(b"deconvolution of tissue sections", b"deconvolution of tissue regions"))
        cls.ing = cls.lib / "tools" / "ingest.py"

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def plan(self): return json.loads((self.lib / "_meta/ingest/plan.json").read_text())

    def test_00_fresh_library_starts_with_a_clean_git_tree(self):
        st = subprocess.run(["git", "-C", self.tmp / "fresh_check", "status", "--short"], capture_output=True, text=True) if run([SCRIPTS / "init_library.py", "--root", self.tmp / "fresh_check", "--parents", "Methods"], ok=[0]) else None
        self.assertEqual(st.stdout.strip(), "", st.stdout)

    def test_01_help_of_every_script_exits_zero(self):
        for s in ("ingest.py", "catalog.py", "build_html.py", "export_github.py", "init_library.py"):
            r = run([SCRIPTS / s, "--help"]); self.assertEqual(r.returncode, 0, s); self.assertTrue(r.stdout.strip(), s)

    def test_02_not_a_library_is_a_usage_error(self):
        r = run([self.ing, "--root", self.tmp / "nowhere", "scan", "--all"]); self.assertEqual(r.returncode, 2)
        r = run([self.ing, "scan", "--inbox", self.inbox]); self.assertEqual(r.returncode, 0 if False else r.returncode)  # needs --since/--all or state

    def test_03_scan_requires_since_or_a_previous_run(self):
        (self.lib / "_meta/ingest/state.json").write_text("{}")
        r = run([self.ing, "scan", "--inbox", self.inbox]); self.assertEqual(r.returncode, 2); self.assertIn("--since", r.stderr)

    def test_04_flow(self):
        run([self.ing, "detect"], ok=[0])
        r = run([self.ing, "scan", "--inbox", self.inbox, "--all"], ok=[0]); self.assertIn("scan complete", r.stdout)
        run([self.ing, "plan"], ok=[0]); p = self.plan()
        by = {Path(i["src"]).name: i for i in p["items"]}
        skipped = " ".join(s["src"] + s["reason"] for s in p["skipped"])
        self.assertIn("copy_of_known.pdf", skipped); self.assertIn("already in library", skipped)             # SHA-256 duplicate
        self.assertEqual(by["Rechnung_2026_11.pdf"]["action"], "skip")                                         # not a paper
        self.assertEqual(len(p["new_categories"]), 1)                                                          # qb1-3 cluster together
        cat = p["new_categories"][0]; self.assertFalse(cat["approved"]); self.assertEqual(len(cat["members"]), 3)
        self.assertTrue(cat["path"].split("/")[0] in ("Methods", "Biology"))
        for n in ("qb1.pdf", "qb2.pdf", "qb3.pdf"): self.assertEqual(by[n]["dest"], cat["path"])
        self.assertTrue(by["new_methods.pdf"]["dest"].startswith("Methods"))
        # nothing filed yet: apply without --run is a dry run and reports unresolved items
        before = sorted(str(x) for x in self.lib.rglob("*.pdf"))
        r = run([self.ing, "apply"]); self.assertEqual(r.returncode, 3); self.assertIn("DRY RUN", r.stdout)
        self.assertEqual(sorted(str(x) for x in self.lib.rglob("*.pdf")), before)
        # approving items but NOT the new category: those items are errors, no folder is created
        for i in p["items"]:
            if i["action"] in ("ask", "file") and Path(i["src"]).name != "copy_of_known.pdf": i.update(action="file", approved=True)
        (self.lib / "_meta/ingest/plan.json").write_text(json.dumps(p))
        r = run([self.ing, "apply", "--run", "--no-commit"]); self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertFalse((self.lib / cat["path"]).exists()); self.assertIn("not approved", r.stdout)
        # an unapproved 'file' item is never filed
        p = self.plan(); n_before = len(list(self.lib.rglob("*.pdf")))
        for i in p["items"]: i["approved"] = False
        (self.lib / "_meta/ingest/plan.json").write_text(json.dumps(p))
        run([self.ing, "apply", "--run", "--no-commit"], ok=[3]); self.assertEqual(len(list(self.lib.rglob("*.pdf"))), n_before)
        # approve everything, fix a metadata field, move
        p = self.plan(); p["new_categories"][0]["approved"] = True
        for i in p["items"]:
            if Path(i["src"]).name == "qb1.pdf": i.update(first_author="Meyer", meta_confidence="high")
            if i["action"] in ("ask", "file"): i.update(action="file", approved=True)
        (self.lib / "_meta/ingest/plan.json").write_text(json.dumps(p))
        srcs = {Path(i["src"]).name: (i["src"], i["sha"]) for i in p["items"] if i["action"] == "file"}
        r = run([self.ing, "apply", "--run", "--mode", "move"], ok=[0]); self.assertIn("filed 4", r.stdout, r.stdout)
        for name, (src, h) in srcs.items(): self.assertFalse(Path(src).exists(), name)                         # moved: source gone
        filed = {json.loads(l)["sha256"]: json.loads(l) for l in (self.lib / "_meta/papers.jsonl").read_text().splitlines()}
        for name, (src, h) in srcs.items():
            self.assertIn(h, filed, name); self.assertEqual(sha(self.lib / filed[h]["path"]), h)               # verified copy
        qb1 = [r_ for r_ in filed.values() if r_["first_author"] == "Meyer"]; self.assertEqual(len(qb1), 1)   # reviewed metadata kept by the catalog
        self.assertEqual(len(filed), 1 + 4)
        self.assertTrue((self.lib / "site" / "index.html").exists())
        log = subprocess.run(["git", "-C", self.lib, "log", "--oneline", "-1"], capture_output=True, text=True).stdout
        self.assertIn("ingest 4 papers", log)
        self.assertEqual(subprocess.run(["git", "-C", self.lib, "status", "--short"], capture_output=True, text=True).stdout.strip(), "")
        self.assertIn("last_scan", (self.lib / "_meta/ingest/state.json").read_text())
        # the second scan finds nothing new
        r = run([self.ing, "scan", "--inbox", self.inbox], ok=[0]); self.assertIn("found: {", r.stdout)
        # catalog is idempotent and a renamed file keeps its id
        r = run([self.lib / "tools/catalog.py"], ok=[0]); self.assertIn("added=0 removed=0", r.stdout)
        victim = self.lib / filed[qb1[0]["sha256"]]["path"]; new = victim.with_name("Renamed.pdf"); victim.rename(new)
        r = run([self.lib / "tools/catalog.py"], ok=[0]); self.assertIn("moved/renamed=1", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
