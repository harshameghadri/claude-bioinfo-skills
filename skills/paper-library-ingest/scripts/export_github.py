#!/usr/bin/env python3
"""Build export/ = the allow-listed, PDF-free mirror meant for a private GitHub repo.
Included: catalog.csv, papers.jsonl, highlight_schema.json, legacy manifests, HTML pages (no PDF links, no highlight quotes).
Never included: PDFs, AGENTS.md, _meta/notes (quotes), docs/, tools/provenance.
Then:  cd export && git init -b main (first time) && git add -A && git commit -m ... && git push"""
import os,shutil,subprocess,sys,datetime
import argparse
ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('--root',help='library root (default: parent of this script folder)'); a=ap.parse_args()
ROOT=os.path.abspath(os.path.expanduser(a.root or os.path.join(os.path.dirname(os.path.abspath(__file__)),'..'))); OUT=f'{ROOT}/export'
if not os.path.exists(f'{ROOT}/_meta/papers.jsonl'): print(f'{ROOT} is not a library. Pass --root DIR.',file=sys.stderr); sys.exit(2)
keep_git=os.path.isdir(f'{OUT}/.git')
if os.path.isdir(OUT):
    for n in os.listdir(OUT):
        if n=='.git': continue
        p=os.path.join(OUT,n); shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
os.makedirs(f'{OUT}/_meta/legacy',exist_ok=True)
for f in ('catalog.csv','papers.jsonl','highlight_schema.json'): shutil.copy2(f'{ROOT}/_meta/{f}',f'{OUT}/_meta/{f}')
for f in os.listdir(f'{ROOT}/_meta/legacy'):
    if f.endswith('.csv'): shutil.copy2(f'{ROOT}/_meta/legacy/{f}',f'{OUT}/_meta/legacy/{f}')
subprocess.run([sys.executable,os.path.join(os.path.dirname(os.path.abspath(__file__)),'build_html.py'),'--root',ROOT,'--out',f'{OUT}/site','--export'],check=True)
open(f'{OUT}/README.md','w').write(f"""# {os.path.basename(ROOT)} - catalog mirror (no PDFs)

Generated {datetime.date.today()} from the private library. Contains metadata only:
`_meta/catalog.csv`, `_meta/papers.jsonl` (per-paper record incl. summary fields), manifests, and per-category HTML pages in `site/`
(download and open locally - GitHub shows HTML as source). PDFs, highlight quotes and agent instructions live only on the main copy.
""")
print('export ready:',OUT)
