#!/usr/bin/env python3
"""Create a new paper library that the paper-library-ingest skill can maintain.
Usage: python3 init_library.py --root ~/Documents/PaperLibrary [--parents "Methods,Biology,Clinical"] [--collection "Name:regex[:min_hits]" ...]
Creates: tools/ (ingest, catalog, html, commit scripts), _meta/ (schema, ingest state), .gitignore, .gitattributes, AGENTS.md, README.md, git repo."""
import os,sys,json,shutil,argparse,subprocess
ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ap.add_argument('--parents',default='Methods,Biology,Clinical',help='top-level folders new categories may be created under')
ap.add_argument('--collection',action='append',default=[],help='optional topic collection that wins over topical folders: "Folder/Name:regex[:min_hits]"'); ap.add_argument('--no-git',action='store_true')
a=ap.parse_args(); R=os.path.abspath(os.path.expanduser(a.root)); HERE=os.path.dirname(os.path.abspath(__file__))
if os.path.exists(f'{R}/_meta/papers.jsonl'): print('library already initialised here',file=sys.stderr); sys.exit(2)
for d in ('tools','_meta/notes','_meta/ingest','docs','site'): os.makedirs(f'{R}/{d}',exist_ok=True)
for f in ('ingest.py','catalog.py','build_html.py','commit.sh','export_github.py'):
    if os.path.exists(f'{HERE}/{f}'): shutil.copy2(f'{HERE}/{f}',f'{R}/tools/{f}')
open(f'{R}/_meta/notes/.gitkeep','w').close()
parents=[p.strip() for p in a.parents.split(',') if p.strip()]; [os.makedirs(f'{R}/{p}',exist_ok=True) for p in parents]
colls=[]
for c in a.collection:
    parts=c.split(':'); colls.append(dict(path=parts[0],pattern=parts[1],min_hits=int(parts[2]) if len(parts)>2 else 2)); os.makedirs(f'{R}/{parts[0]}',exist_ok=True)
json.dump(dict(collections=colls,new_category_parents=parents,exclude_dirs=[]),open(f'{R}/_meta/ingest/config.json','w'),indent=1)
import datetime; json.dump({'last_scan':datetime.datetime.now().isoformat(timespec='seconds')},open(f'{R}/_meta/ingest/state.json','w')); json.dump([],open(f'{R}/_meta/ingest/ignore.json','w'))
json.dump(dict(version=1,status='DRAFT - edit freely but keep ids stable',colors=[dict(id='yellow',hex='#f5d90a',name='Key claim / finding'),dict(id='green',hex='#2fb344',name='Method worth reusing'),dict(id='blue',hex='#3e63dd',name='Definition / background'),dict(id='red',hex='#e5484d',name='Limitation / doubt / contradiction'),dict(id='purple',hex='#8e4ec6',name='Idea for own work')],notes_file='_meta/notes/<paper id>.json'),open(f'{R}/_meta/highlight_schema.json','w'),indent=1)
open(f'{R}/.gitignore','w').write('.DS_Store\n__pycache__\n*.pyc\n_meta/.sha_cache.json\nexport/\n*.tmp\n~$*\n_meta/ingest/scan.json\n_meta/ingest/plan.json\n_meta/ingest/seen.json\n')
open(f'{R}/.gitattributes','w').write('*.pdf binary\n*.csv text eol=lf\n*.jsonl text eol=lf\n*.json text eol=lf\n*.md text eol=lf\n*.html text eol=lf\n*.py text eol=lf\n*.sh text eol=lf\n')
open(f'{R}/README.md','w').write(f'# {os.path.basename(R)}\nPaper library maintained with the paper-library-ingest skill. Catalog: `_meta/catalog.csv`. Browse: `site/index.html`. Add papers: `tools/commit.sh "reason"`; ingest from download folders: see `skills/paper-library-ingest/SKILL.md` (or the copy in your agent skills folder).\n')
open(f'{R}/AGENTS.md','w').write('# AGENTS.md\nSource of truth: `_meta/papers.jsonl` (one record per paper, id = p_ + first 12 hex of the PDF SHA-256). `_meta/catalog.csv`, `site/` are generated: never hand-edit.\nCommands: `python3 tools/catalog.py`, `python3 tools/build_html.py`, `tools/commit.sh "reason"`, `python3 tools/ingest.py detect|scan|plan|apply` (follow the paper-library-ingest skill).\nSummaries: read the PDF, 3 key findings each with a page reference, `verified:false` until the owner checks. Never invent metadata. Keep any remote private (copyright).\n')
subprocess.run([sys.executable,f'{R}/tools/catalog.py'],cwd=R)   # generate _meta/catalog.csv and papers.jsonl BEFORE the first commit so the new library starts clean
if not a.no_git:
    for c in (['git','init','-q','-b','main'],['git','add','-A']): subprocess.run(c,cwd=R,capture_output=True)
    r=subprocess.run(['git','commit','-q','-m','init library'],cwd=R,capture_output=True,text=True)
    if r.returncode: print('NOTE: git commit failed (set git config --global user.name / user.email, then run: git add -A && git commit -m init). Detail:',r.stderr.strip().splitlines()[0] if r.stderr.strip() else '')
print('library ready:',R,'| parents:',parents,'| collections:',[c['path'] for c in colls])
