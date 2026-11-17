#!/usr/bin/env python3
"""Validate every skills/*/ folder against docs/SKILL_STANDARD.md. Standard library only.

Usage: python3 scripts/validate_skills.py [--skill NAME ...] [--no-exec] [--strict] [--private-patterns FILE]
  --no-exec    do not run any script (skips the --help execution checks; syntax checks still run if the interpreters exist)
  --strict     treat warnings as errors
  --private-patterns FILE   extra regular expressions (one per line) that must not appear anywhere; kept OUT of the repository
                            (also read from $SKILL_PRIVATE_PATTERNS and ./.private-patterns when present)
Exit codes: 0 ok, 1 errors found, 2 usage.
"""
import argparse, json, os, py_compile, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(os.environ.get("SKILL_REPO_ROOT") or Path(__file__).resolve().parent.parent)
SKILLS = ROOT / "skills"
errors, warnings = [], []


def err(skill, msg): errors.append(f"ERROR {skill}: {msg}")
def warn(skill, msg): warnings.append(f"WARN  {skill}: {msg}")


# Names of one vendor's tools and harness paths must not appear in skill text: another model has no such tools.
TOOL_PATTERNS = [
    (r"\bmcp__\w+", "MCP tool identifier"),
    (r"\b(?:the\s+)?(?:Bash|Read|Write|Edit|MultiEdit|Grep|Glob|WebFetch|WebSearch|TodoWrite|NotebookEdit|AskUserQuestion|SendUserFile|SendUserMessage|Skill|Task|Agent)\s+tool\b", "named harness tool"),
    (r"\b(?:use|call|invoke)\s+(?:the\s+)?(?:Bash|Read|Write|Edit|Grep|Glob|WebFetch|WebSearch|TodoWrite|AskUserQuestion)\b", "instruction to call a named harness tool"),
    (r"/mnt/user-data|/mnt/skills|/mnt/project-files", "harness path"),
]
# Generic hygiene (no private names are listed here on purpose).
HYGIENE = [
    (r"/Users/[A-Za-z0-9._-]+", "macOS home path"),
    (r"/home/(?!user\b|you\b|claude\b)[A-Za-z0-9._-]+", "Linux home path"),
    (r"/Volumes/[A-Za-z0-9._ -]+", "macOS volume path"),
    (r"[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com|example\.|email\.com|anthropic\.com)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:com|org|net|edu|gov|io|de|se|uk|ch|fr|nl|eu|ai|co|info)\b", "email address"),
    (r"\b[a-z0-9-]+\.ts\.net\b", "tailnet hostname"),
    (r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}", "GitHub token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS key id"),
    (r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY", "private key"),
    (r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b", "private IP address"),
]
TEXT_EXT = {".md", ".py", ".R", ".r", ".sh", ".yml", ".yaml", ".json", ".txt", ".tsv", ".csv", ".gtf", ".gff3", ".fa", ".toml", ".cfg", ".qmd", ".Rmd"}
BANNED_FILES = {".DS_Store", "Thumbs.db"}
MAX_SKILL_MD_LINES = 500
MAX_FILE_BYTES = 2_000_000


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else None


def run(cmd, timeout=60, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)


def check_frontmatter(skill, text):
    fm = frontmatter(text)
    if fm is None:
        err(skill, "SKILL.md has no YAML frontmatter"); return
    name = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
    desc = re.search(r"^description:\s*(.+?)(?=\n[A-Za-z_-]+:|\Z)", fm, re.M | re.S)
    if not name or name.group(1) != skill:
        err(skill, "'name' must equal the folder name")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", skill) or len(skill) > 64:
        err(skill, "folder/name must be lowercase letters, digits and single hyphens, at most 64 characters")
    if not desc or not desc.group(1).strip():
        err(skill, "empty description"); return
    d = " ".join(re.sub(r"^[>|][+-]?\s*", "", desc.group(1).strip()).split())   # drop the YAML folded/literal marker
    if len(d) > 1024:
        err(skill, f"description is {len(d)} characters; the limit is 1024")
    if len(d) < 80:
        warn(skill, "description is very short; it is the trigger and should say what the skill does and when to use it")
    if "<" in d or ">" in d:
        err(skill, "description must not contain angle brackets")
    if re.search(r"authoring_session|published_by", fm):
        err(skill, "session metadata should be stripped before publishing")


def check_references(skill, folder, text):
    """Paths written in backticks or links that start with scripts/, references/, tests/ must exist (unless they are templates)."""
    for m in re.finditer(r"(?:`|\()((?:scripts|references|tests|assets)/[A-Za-z0-9_./-]+)", text):
        p = m.group(1).rstrip(".,)")
        if any(c in p for c in "<>*{}") or p.endswith("/"):      # templates and directories to create in the user's project
            continue
        if not (folder / p).exists():
            err(skill, f"SKILL.md refers to {p}, which does not exist")


def scan_text(skill, rel, text, patterns, kind, severity=err):
    for rx, label in patterns:
        for m in re.finditer(rx, text):
            line = text.count("\n", 0, m.start()) + 1
            severity(skill, f"{rel}:{line}: {label} ({kind}): {m.group(0)[:60]}")
            break


def check_scripts(skill, folder, no_exec):
    scripts = folder / "scripts"
    if not scripts.is_dir():
        return
    have_rscript = shutil.which("Rscript") is not None
    shellcheck = shutil.which("shellcheck")
    for f in sorted(p for p in scripts.rglob("*") if p.is_file()):
        rel = f.relative_to(folder)
        text = f.read_text(encoding="utf-8", errors="replace")
        first = text.splitlines()[0] if text else ""
        if f.suffix == ".py":
            try:
                with tempfile.TemporaryDirectory() as td:
                    py_compile.compile(str(f), cfile=os.path.join(td, "x.pyc"), doraise=True)
            except py_compile.PyCompileError as e:
                err(skill, f"{rel}: does not compile: {e.msg.strip()[:120]}"); continue
            if '__name__ == "__main__"' in text or "__name__ == '__main__'" in text:
                if not first.startswith("#!"):
                    warn(skill, f"{rel}: command-line script without a shebang line")
                if not os.access(f, os.X_OK):
                    warn(skill, f"{rel}: command-line script is not executable")
                if not no_exec:
                    r = run([sys.executable, "-I", str(f), "--help"], timeout=30)
                    if r.returncode != 0 or not (r.stdout.strip() or r.stderr.strip()):
                        err(skill, f"{rel}: '--help' must exit 0 and print usage (exit {r.returncode})")
        elif f.suffix in (".R", ".r"):
            cli = first.startswith("#!") and "Rscript" in first
            if have_rscript:
                r = run(["Rscript", "-e", f"invisible(parse('{f}'))"], timeout=60)
                if r.returncode != 0:
                    err(skill, f"{rel}: R parse error: {r.stderr.strip()[:160]}"); continue
            if cli:
                if not no_exec and have_rscript:
                    r = run(["Rscript", str(f), "--help"], timeout=120)
                    if r.returncode != 0 or not (r.stdout.strip() or r.stderr.strip()):
                        err(skill, f"{rel}: '--help' must exit 0 and print usage (exit {r.returncode})")
                if not os.access(f, os.X_OK):
                    warn(skill, f"{rel}: command-line script is not executable")
        elif f.suffix == ".sh":
            r = run(["bash", "-n", str(f)])
            if r.returncode != 0:
                err(skill, f"{rel}: bash syntax error: {r.stderr.strip()[:160]}")
            if shellcheck:
                r = run([shellcheck, "-S", "warning", str(f)])
                if r.returncode != 0:
                    err(skill, f"{rel}: shellcheck: {r.stdout.strip().splitlines()[0] if r.stdout.strip() else 'findings'}")


def check_tests(skill, folder):
    if (folder / "scripts").is_dir() and any(p.is_file() for p in (folder / "scripts").rglob("*")):
        run_sh = folder / "tests" / "run.sh"
        if not run_sh.exists():
            err(skill, "skill has scripts/ but no tests/run.sh (see docs/SKILL_STANDARD.md)")
        elif not os.access(run_sh, os.X_OK):
            warn(skill, "tests/run.sh is not executable")


def visible_files(folder):
    """Files git would commit (tracked or untracked and not ignored); every file when git is unavailable."""
    try:
        r = subprocess.run(["git", "-C", str(folder), "ls-files", "-co", "--exclude-standard", "-z", "--", "."], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return sorted(folder / n for n in r.stdout.split("\0") if n and (folder / n).exists())
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(folder.rglob("*"))


def check_files(skill, folder, patterns):
    for p in visible_files(folder):
        rel = p.relative_to(folder)
        if p.is_dir():
            if p.name in ("__pycache__", ".pytest_cache", ".ipynb_checkpoints", ".Rproj.user"):
                err(skill, f"{rel}: build/cache directory must not be committed")
            continue
        if p.name in BANNED_FILES or p.suffix in (".pyc", ".pyo", ".swp"):
            err(skill, f"{rel}: junk file must not be committed")
        if p.stat().st_size > MAX_FILE_BYTES:
            err(skill, f"{rel}: {p.stat().st_size // 1000} kB exceeds the {MAX_FILE_BYTES // 1000} kB limit; generate large fixtures in the tests instead")
        if p.suffix in TEXT_EXT or p.name in ("LICENSE",):
            text = p.read_text(encoding="utf-8", errors="replace")
            scan_text(skill, str(rel), text, HYGIENE, "hygiene")
            for rx in patterns:
                m = re.search(rx, text, re.I)
                if m:
                    err(skill, f"{rel}: matches a private pattern ({m.group(0)[:3]}...)")
            if p.suffix == ".md":
                scan_text(skill, str(rel), text, TOOL_PATTERNS, "vendor-specific")


def check_skill(folder, args, patterns):
    skill = folder.name
    md = folder / "SKILL.md"
    text = md.read_text(encoding="utf-8")
    check_frontmatter(skill, text)
    n = text.count("\n") + 1
    if n > MAX_SKILL_MD_LINES:
        warn(skill, f"SKILL.md has {n} lines (target at most {MAX_SKILL_MD_LINES}); move detail to references/")
    check_references(skill, folder, text)
    check_scripts(skill, folder, args.no_exec)
    check_tests(skill, folder)
    check_files(skill, folder, patterns)


def check_repo(skills):
    for rel in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
        p = ROOT / rel
        if not p.exists():
            err("repo", f"{rel} missing"); continue
        try:
            json.loads(p.read_text())
        except json.JSONDecodeError as e:
            err("repo", f"{rel} is not valid JSON: {e}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    for s in skills:
        if f"skills/{s}" not in readme:
            err("repo", f"README.md does not list skill '{s}'")
    if (ROOT / "docs" / "SKILL_STANDARD.md").exists() is False:
        err("repo", "docs/SKILL_STANDARD.md missing")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", action="append", help="only this skill folder (repeatable)")
    ap.add_argument("--no-exec", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--private-patterns")
    args = ap.parse_args()
    pats = []
    for f in filter(None, [args.private_patterns, os.environ.get("SKILL_PRIVATE_PATTERNS"), str(ROOT / ".private-patterns")]):
        if os.path.isfile(f):
            pats += [l.strip() for l in Path(f).read_text().splitlines() if l.strip() and not l.startswith("#")]
    folders = sorted(p for p in SKILLS.iterdir() if p.is_dir())
    if args.skill:
        missing = set(args.skill) - {f.name for f in folders}
        if missing:
            print(f"unknown skill(s): {', '.join(sorted(missing))}", file=sys.stderr); return 2
        folders = [f for f in folders if f.name in args.skill]
    for f in folders:
        if not (f / "SKILL.md").exists():
            err(f.name, "no SKILL.md")
            continue
        check_skill(f, args, pats)
    if not args.skill:
        check_repo([f.name for f in folders])
    for line in warnings + errors:
        print(line)
    bad = errors or (args.strict and warnings)
    print(f"{'FAILED' if bad else 'OK'}: {len(folders)} skill(s), {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
