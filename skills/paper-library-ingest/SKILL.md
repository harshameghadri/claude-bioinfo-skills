---
name: paper-library-ingest
description: Keeps a personal library of scientific PDFs organised and version-controlled. Detects download folders (Downloads, Documents, Desktop, Zotero, browser download locations), finds new PDFs, drops non-papers such as invoices and CVs, proposes a category per paper, asks before creating any new category, files approved papers with SHA-256 verification, rebuilds a catalog and per-category HTML pages, and commits to git. Can also create a new empty library. Use when the user says things like "file the new papers", "organise my downloaded PDFs", "add these papers to my library", "sort my paper folder", "create a paper library".
---

# paper-library-ingest

Requirements: `python3` (3.8+, standard library only), `git` with `user.name` and `user.email` set, and poppler (`pdftotext`, `pdfinfo`). macOS or Linux. The scripts are in `scripts/`; `scripts/init_library.py` copies them into each library as `tools/`, and the commands below are written for that copy (run them from the library folder).

The scripts do everything that can be deterministic (scan, hash, dedupe, plan, copy with verification, catalog, HTML, commit). Your part is judgement: check the guessed metadata against page 1, ask the user the questions in step 5, and report honestly. Do not skip a step marked GATE.

## Rules that prevent known failures
1. Nothing is filed, moved or deleted without the user's approval. `apply` is a dry run unless `--run` is given, and it files only items with `"action":"file"` AND `"approved":true`.
2. Default mode is copy. Use `--mode move` only if the user asks. Move deletes the source only after a byte-identical, SHA-256-verified copy; if deletion is not permitted the source goes to `_to_delete/` beside it.
3. Never invent metadata. Title, first author, year and DOI are heuristics from page 1; correct them from the page text, or leave `Unknown`.
4. Never hand-edit generated files (`_meta/papers.jsonl`, `_meta/catalog.csv`, `site/`). Corrected metadata goes into `plan.json` before `apply`.
5. One physical copy per paper. A configured collection (`_meta/ingest/config.json`) wins over topical folders.
6. The classifier is a suggestion. Measured accuracy of the exact folder: 55-60% on one real library of 474 papers with about 40 overlapping folders; 93% (leave-one-out) on a 10-folder library of well-separated topics, falling to 80% with 3 library papers per folder and 57% with 1. Verdict `high` was right 92-100% of the time once folders held 2 or more papers, but when a paper's topic has no folder yet about 1 in 10 still gets a wrong `high`. So the user sees the whole plan, and a paper whose subject no folder name covers is a new-category candidate whatever its verdict.
7. A scan with no recorded previous run needs `--since YYYY-MM-DD` or `--all`; otherwise it exits 2.
8. If a command fails with an error you do not understand, stop and report it. Do not retry in a loop or work around it.
9. Keep any remote repository private: the library may contain copyrighted PDFs and quoted highlights.

## Procedure

### 1. Find or create the library
A library is a folder containing `_meta/papers.jsonl` and `tools/ingest.py`. Look in the current folder and its parents; otherwise ask the user for the path.
If none exists, ask: where to create it; which top-level folders new categories may go under (for example `Methods,Biology,Clinical`); optional topic collections (`Folder/Name:regex`). Then run
`python3 scripts/init_library.py --root PATH --parents "A,B,C" [--collection "Folder/Name:regex:2"]`.
It prints a note if git has no identity; ask the user to set it and commit manually. An empty library has nothing to match against, so every paper becomes a question for the user.
Then `cd` into the library, read its `AGENTS.md` if present, and run `git status --short`. If it is not empty, show the changes and ask whether to commit them first (`tools/commit.sh "manual changes"`). Do not continue with a dirty tree.

### 2. Detect inbox folders
`python3 tools/ingest.py detect` lists existing candidate folders (Downloads, Desktop, Documents, Zotero storage, browser download folders when their settings are readable) with PDF counts. Tell the user which folders will be scanned. Never scan the library itself or the folders listed under `exclude_dirs` in `_meta/ingest/config.json`. If a folder the user downloads into is missing (not mounted, or outside what you can read), ask the user to make it available; do not guess paths.

### 3. Scan
`python3 tools/ingest.py scan` reads files newer than the last successful run (`_meta/ingest/state.json`).
- First run or a long gap: add `--since YYYY-MM-DD` or `--all` (slow). Use the date the user names; with no date, use `--all` if `detect` showed a few hundred PDFs or fewer, otherwise ask the user for a start date.
- `--inbox PATH` (repeatable) overrides the default folders.
- Output `INCOMPLETE: N files not yet read` means the time budget ended: run the same command again until it prints `scan complete`. Results are cached.
- `found: {}` means nothing new: tell the user and stop.

### 4. Plan, then review it yourself
`python3 tools/ingest.py plan` writes `_meta/ingest/plan.json` with:
- `items[]`: `action` (`file` likely match, `ask` needs a decision, `skip` not a paper), `approved` (false), `dest`, `top3`, `reason`, guessed `title`, `first_author`, `year`, `venue_abbr`, `doi`, and `page1_text`.
- `new_categories[]`: proposed folders for unmatched papers that resemble each other (`approved: false`, `parents` lists the allowed parents).
- `skipped[]`: files already in the library (same SHA-256) or duplicated in the batch. Report only their number.

For every item whose action is not `skip`:
1. Compare the guessed metadata with `page1_text` and correct `title`, `first_author` (surname only), `year`, `venue_abbr` (short, no spaces, for example `NatMethods`, `bioRxiv`; if page 1 prints only the full journal name, join its initials or its main words, for example `Journal of Synthetic Examples` becomes `JSynthExamples`; if no journal is printed, `Unknown`), `doi` where the text shows them. Replace obvious garbage (a date line, "arXiv:...", "Running Title"). After correcting, set `"meta_confidence": "high"`.
2. Check `dest` against `existing_folders`; change it if wrong. A new folder name is `Title_Case_With_Underscores` under an allowed parent.
3. For "possible duplicate": a preprint and its published version are different records, keep both; the same version twice is `"action": "ignore"`; unsure means leave `ask` and put the question to the user in step 5; do not decide it yourself.

### 5. GATE: ask the user (one grouped message, then wait for the answers)
1. For each entry of `new_categories`: "N papers match no existing category: TITLES. Create PARENT/NAME? yes / yes with another name or parent / no, file elsewhere / skip." Never create a category without a yes. Single unmatched papers: file under the closest folder, create a category, or skip?
2. Each `ask` item: title, proposed folder, runner-up folder.
3. Titles of files you doubt were skipped correctly.
4. Mode: copy (default) or move.
Then show the final table (inbox file, destination folder, new file name `Author_Year_Venue_Short-title.pdf`) and ask "Apply this?" Wait for an explicit yes.

### 6. Apply
1. Edit `plan.json` to match the answers: approved items `"action": "file"`, `"approved": true`, `dest`; "never show again" `"action": "ignore"`; "not now" `"action": "skip"`. For each approved new category set `"approved": true`; if it was renamed, change `path` and the `dest` of its members to the same value. Items left as `ask` stay pending and the scan watermark does not advance.
2. Dry run: `python3 tools/ingest.py apply` (add `--mode move` if chosen). It prints each source and target and exits 3 if anything is unresolved or unapproved. Fix and repeat until the listed problems are the ones you expect.
3. Run: `python3 tools/ingest.py apply --run` (plus `--mode move` if chosen). It copies with SHA-256 verification, creates approved categories, records metadata in `_meta/ingest_meta.json`, runs `tools/catalog.py` and `tools/build_html.py`, and commits as `ingest N papers`. `--no-commit` skips the commit.
4. Exit codes of `ingest.py`: 0 ok; 2 usage, not a library, or a missing earlier step; 3 needs attention (errors listed, or items still unresolved or unapproved); 4 a copy did not verify. After 3, fix the plan and run again; apply is safe to repeat. After 4 stop and report; do not loop.

### 7. Verify (never skip)
- `git status --short` is empty and `git log --oneline -1` shows the ingest commit.
- The number of lines in `_meta/papers.jsonl` equals the previous number plus the number filed.
- Each filed file exists at its destination and `sha256sum` equals `sha` in the plan.
- Each new category has a page `site/SLUG.html`, where SLUG is the folder path in lower case with `/` and `_` replaced by `-` (`Biology/Quantum_Biology` gives `site/biology-quantum-biology.html`); check with `grep -c 'class="paper"' site/SLUG.html`.
- Move mode: sources are gone or in `_to_delete/`.
If a check fails, say exactly which one; never report success.

### 8. Record new categories
If a category was created, read `AGENTS.md`, append `- DATE: PATH created for N papers (reason)` to `docs/TAXONOMY.md` (create it if absent), append the line `- Category PATH: one-line description` to `AGENTS.md`, and run `tools/commit.sh "docs: new category NAME"` (one commit for all categories created in this run, with their names in the message).

### 9. Report (short)
Counts scanned, filed, skipped, pending; new categories; where originals went; the commit hash. Files skipped as already in the library stay where they are even in move mode: list them and offer to delete them, and delete only if the user says yes. Remind only if relevant: summaries of new papers are `pending`; pushing to a remote is the user's step; `python3 tools/export_github.py` refreshes a PDF-free export.

## Failure table
| Symptom | Action |
|---|---|
| `No previous scan recorded` (exit 2) | re-run with `--since YYYY-MM-DD` or `--all` |
| `is not a library` (exit 2) | pass `--root DIR` or create a library (step 1) |
| `INCOMPLETE` | run scan again |
| `category ... not approved` (exit 3) | ask the user, set `approved: true` on that category or change `dest` |
| `copy verify failed` (exit 4) | disk or permission problem; stop and report |
| `.git/index.lock` exists | make sure no git process runs, remove the lock, run again |
| garbage title or `Unknown` author | correct it from `page1_text`, otherwise keep and tell the user |
| scanned PDF without a text layer | listed as borderline; ask the user |

## Outputs
Per library: `_meta/papers.jsonl` (source of truth, one record per paper, id `p_` + first 12 hex of the SHA-256), `_meta/catalog.csv`, `site/*.html` (foldable per-category pages), `_meta/ingest_meta.json`, `_meta/ingest/{config,state,ignore}.json` and `log.jsonl` (tracked), `_meta/ingest/{scan,plan,seen}.json` (scratch, ignored by git). Per-paper summary fields start as `pending` and `verified: false`; highlights belong in `_meta/notes/ID.json` with colours from `_meta/highlight_schema.json`.

## How this skill is tested
`bash tests/run.sh` (offline, a few seconds) builds a library and synthetic PDFs, then checks: every script's `--help`; usage errors and exit codes; duplicate detection by SHA-256; non-paper skipping; clustering of three similar unmatched papers into one proposed category; dry run writes nothing; unapproved items and unapproved categories are never filed; verified move; reviewed metadata survives the catalog rebuild; the git commit; second scan finds nothing; catalog idempotence and rename detection. It is skipped with a printed reason if poppler is missing.

## Not verified
Classifier accuracy on real PDFs outside the two data sets above (`tests/bench_classifier.py` reproduces the second one; it uses abstracts as page-1 text). Metadata guesses on real journal layouts (they are heuristics). Browser download-folder detection from Chrome, Firefox and Safari settings (code paths exist; only the standard folders are exercised). Scanned PDFs without text. Libraries above a few thousand PDFs (first scan is slow; it resumes). The optional `export_github.py` mirror is not covered by the tests.
