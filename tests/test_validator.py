"""Tests for scripts/validate_skills.py: each rule must fire on a deliberately bad skill and stay quiet on a good one."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parent.parent / "scripts" / "validate_skills.py"
GOOD_DESC = "Example skill that does a specific, testable thing for bioinformatics data. Use for example tasks, demonstrations and checks of the validator."


def make_repo(files):
    root = Path(tempfile.mkdtemp())
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text("{}")
    (root / ".claude-plugin" / "marketplace.json").write_text("{}")
    (root / "docs").mkdir(); (root / "docs" / "SKILL_STANDARD.md").write_text("x")
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        if rel.endswith((".py", ".sh")) and content.startswith("#!"):
            p.chmod(0o755)
    names = sorted({Path(r).parts[1] for r in files if r.startswith("skills/")})
    (root / "README.md").write_text("\n".join(f"skills/{n}" for n in names))
    return root


def validate(root, *args):
    env = dict(os.environ, SKILL_REPO_ROOT=str(root))
    r = subprocess.run([sys.executable, str(VALIDATOR), *args], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout


def skill_md(name="demo", desc=GOOD_DESC, body="Body.\n"):
    return f"---\nname: {name}\ndescription: {desc}\n---\n{body}"


class Validator(unittest.TestCase):
    def tearDown(self):
        for r in getattr(self, "roots", []):
            shutil.rmtree(r, True)

    def run_case(self, files, *args):
        root = make_repo(files); self.roots = getattr(self, "roots", []) + [root]
        return validate(root, *args)

    def assertFlags(self, files, text, *args):
        rc, out = self.run_case(files, *args)
        self.assertEqual(rc, 1, out); self.assertIn(text, out)

    def test_good_skill_passes(self):
        rc, out = self.run_case({"skills/demo/SKILL.md": skill_md()})
        self.assertEqual(rc, 0, out)

    def test_name_must_match_folder(self):
        self.assertFlags({"skills/demo/SKILL.md": skill_md(name="other")}, "'name' must equal")

    def test_description_limits(self):
        self.assertFlags({"skills/demo/SKILL.md": skill_md(desc="x" * 1100)}, "limit is 1024")
        self.assertFlags({"skills/demo/SKILL.md": skill_md(desc="Use <tags> in description " + "word " * 20)}, "angle brackets")

    def test_folded_description_marker_is_not_an_angle_bracket(self):
        md = f"---\nname: demo\ndescription: >\n  {GOOD_DESC}\n  More text.\n---\nBody\n"
        rc, out = self.run_case({"skills/demo/SKILL.md": md})
        self.assertEqual(rc, 0, out)

    def test_missing_reference_file(self):
        self.assertFlags({"skills/demo/SKILL.md": skill_md(body="See `references/nope.md`.\n")}, "does not exist")

    def test_template_and_directory_references_are_ignored(self):
        rc, out = self.run_case({"skills/demo/SKILL.md": skill_md(body="Create `scripts/02b_x/` and `scripts/<name>.R`.\n")})
        self.assertEqual(rc, 0, out)

    def test_vendor_specific_wording(self):
        for body in ("Use the Bash tool to run it.\n", "Call mcp__server__thing.\n", "Files are in /mnt/user-data/uploads.\n"):
            with self.subTest(body=body):
                self.assertFlags({"skills/demo/SKILL.md": skill_md(body=body)}, "vendor-specific")

    def test_hygiene_patterns(self):
        for body, label in (("path /Users/jane/data\n", "macOS home"), ("mail jane@lab.org\n", "email"), ("ghp_" + "a" * 30 + "\n", "token"),
                            ("host box.tail1234.ts.net\n", "tailnet"), ("ip 192.168.1.20\n", "private IP"), ("/Volumes/Data/x\n", "volume")):
            with self.subTest(label=label):
                self.assertFlags({"skills/demo/SKILL.md": skill_md(body=body)}, "hygiene")

    def test_private_pattern_file(self):
        root = make_repo({"skills/demo/SKILL.md": skill_md(body="mentions secretproject here\n")}); self.roots = [root]
        pf = root / "pat.txt"; pf.write_text("secret.?project\n")
        rc, out = validate(root, "--private-patterns", str(pf))
        self.assertEqual(rc, 1); self.assertIn("private pattern", out)
        self.assertNotIn("secretproject", out)          # the report must not echo the private string

    def test_python_script_needs_working_help_and_tests(self):
        files = {"skills/demo/SKILL.md": skill_md(), "skills/demo/scripts/t.py": "#!/usr/bin/env python3\nimport sys\nif __name__ == '__main__':\n    sys.exit(3)\n"}
        rc, out = self.run_case(files)
        self.assertEqual(rc, 1); self.assertIn("--help", out); self.assertIn("tests/run.sh", out)

    def test_working_cli_with_tests_passes(self):
        files = {"skills/demo/SKILL.md": skill_md(), "skills/demo/tests/run.sh": "#!/usr/bin/env bash\nexit 0\n",
                 "skills/demo/scripts/t.py": "#!/usr/bin/env python3\nimport argparse\nif __name__ == '__main__':\n    argparse.ArgumentParser().parse_args()\n"}
        rc, out = self.run_case(files)
        self.assertEqual(rc, 0, out)

    def test_syntax_errors(self):
        files = {"skills/demo/SKILL.md": skill_md(), "skills/demo/tests/run.sh": "#!/usr/bin/env bash\nexit 0\n", "skills/demo/scripts/bad.py": "def (:\n"}
        self.assertFlags(files, "does not compile")
        files = {"skills/demo/SKILL.md": skill_md(), "skills/demo/tests/run.sh": "#!/usr/bin/env bash\nexit 0\n", "skills/demo/scripts/bad.sh": "#!/usr/bin/env bash\nif then\n"}
        self.assertFlags(files, "syntax error")

    def test_readme_must_list_every_skill(self):
        root = make_repo({"skills/demo/SKILL.md": skill_md()}); self.roots = [root]
        (root / "README.md").write_text("nothing")
        rc, out = validate(root)
        self.assertEqual(rc, 1); self.assertIn("README.md does not list skill 'demo'", out)

    def test_junk_and_large_files(self):
        self.assertFlags({"skills/demo/SKILL.md": skill_md(), "skills/demo/.DS_Store": "x"}, "junk file")

    def test_strict_turns_warnings_into_errors(self):
        short = skill_md(desc="Short description here.")
        rc, out = self.run_case({"skills/demo/SKILL.md": short}); self.assertEqual(rc, 0, out)
        rc, out = self.run_case({"skills/demo/SKILL.md": short}, "--strict"); self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
