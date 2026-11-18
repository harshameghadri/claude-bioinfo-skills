#!/usr/bin/env python3
"""Generate one foldable HTML page per category from _meta/papers.jsonl (+ _meta/notes/*.json).
Never edit the HTML by hand - edit the data and regenerate.
  python3 tools/build_html.py                      -> site/   (local, links to PDFs)
  python3 tools/build_html.py --out DIR --export   -> DIR     (no PDF links, no highlight quotes unless --with-notes)"""
import os,sys,json,html,re,argparse,collections,datetime
ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('--root',help='library root (default: parent of this script folder)'); ap.add_argument('--out',help='output folder (default <root>/site)'); ap.add_argument('--export',action='store_true'); ap.add_argument('--with-notes',action='store_true')
a=ap.parse_args()
ROOT=os.path.abspath(os.path.expanduser(a.root or os.path.join(os.path.dirname(os.path.abspath(__file__)),'..'))); META=f'{ROOT}/_meta'
if not os.path.exists(f'{META}/papers.jsonl'): print(f'{ROOT} is not a library (no _meta/papers.jsonl). Pass --root DIR.',file=sys.stderr); sys.exit(2)
a.out=a.out or f'{ROOT}/site'; os.makedirs(a.out,exist_ok=True)
for f in os.listdir(a.out):
    if f.endswith('.html'): os.remove(os.path.join(a.out,f))
recs=[json.loads(l) for l in open(f'{META}/papers.jsonl',encoding='utf-8')]
schema=json.load(open(f'{META}/highlight_schema.json')); colors={c['id']:c for c in schema['colors']}
E=lambda s:html.escape(str(s)) if s is not None else ''
def notes_of(r):
    p=f"{META}/notes/{r['id']}.json"
    return json.load(open(p,encoding='utf-8')).get('highlights',[]) if os.path.exists(p) else []
CFGP=f'{META}/ingest/config.json'; COLL_TOPS={'0_Disease_Collections'}|({c['path'].split('/')[0] for c in json.load(open(CFGP)).get('collections',[])} if os.path.exists(CFGP) else set())
nice=lambda x:(x.split('_',1)[1] if re.match(r'\d+_',x) else x).replace('_',' ')
pages=collections.OrderedDict()
def add(slug,title,r): pages.setdefault(slug,dict(title=title,recs=[]))['recs'].append(r)
for r in recs:
    p=r['path'].split('/')
    if p[0] in COLL_TOPS and len(p)>=3: add('collection-'+p[1].lower(),f'Collection · {p[1]}',r)
    elif len(p)>=3: add(re.sub(r'[^a-z0-9]+','-',(p[0]+'-'+p[1]).lower()).strip('-'),f"{nice(p[0])} · {p[1].replace('_',' ')}",r)
    else: add(re.sub(r'[^a-z0-9]+','-',p[0].lower()).strip('-'),(nice(p[0].lstrip('_')) if p[0]!='5_Own_Work' else 'Own work'),r)
    if p[0] not in COLL_TOPS:
        for c in r.get('collections',[]): add('collection-'+c.lower(),f'Collection · {c}',r)
CSS="""
:root{--bg:#fff;--fg:#1c2024;--mu:#6b7280;--bd:#e3e5e8;--ac:#3e63dd;--card:#f8f9fb}
@media(prefers-color-scheme:dark){:root{--bg:#111316;--fg:#e6e8eb;--mu:#9aa1ab;--bd:#2a2e34;--ac:#8da4ef;--card:#181b1f}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:980px;margin:0 auto;padding:0 18px 80px}
h1{font-size:22px;margin:22px 0 4px}.sub{color:var(--mu);margin-bottom:12px}
.bar{position:sticky;top:0;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--bd);display:flex;gap:8px;flex-wrap:wrap;z-index:5}
.bar input{flex:1;min-width:200px;padding:7px 10px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg)}
button{padding:6px 11px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}
details.paper{border:1px solid var(--bd);border-radius:10px;margin:10px 0;background:var(--card)}
details.paper>summary{padding:10px 12px;cursor:pointer;list-style:none}
.au{font-weight:600;margin-right:8px}.ti{}.badges{display:block;color:var(--mu);font-size:12px;margin-top:2px}
.pill{display:inline-block;border:1px solid var(--bd);border-radius:99px;padding:0 8px;margin-right:4px;font-size:11px}
.body{padding:2px 14px 12px}.meta{color:var(--mu);font-size:13px;margin-bottom:8px}.meta code{font-size:12px}
details.sec{border-top:1px solid var(--bd);padding:6px 0}details.sec>summary{cursor:pointer;font-weight:600;font-size:13px}
.pending{color:var(--mu);font-style:italic}a{color:var(--ac)}
.hl{border-left:4px solid var(--c);padding:3px 10px;margin:6px 0}.hl q{display:block}.hl small{color:var(--mu)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
ul.idx{list-style:none;padding:0}ul.idx li{padding:7px 0;border-bottom:1px solid var(--bd)}
"""
JS="""
const q=document.getElementById('q'),ps=[...document.querySelectorAll('details.paper')];
function f(){const t=q.value.toLowerCase(),p=document.getElementById('pend').checked;ps.forEach(d=>{d.style.display=(d.textContent.toLowerCase().includes(t)&&(!p||d.dataset.status==='pending'))?'':'none'})}
q.oninput=f;document.getElementById('pend').onchange=f;
document.getElementById('ex').onclick=()=>ps.forEach(d=>d.open=true);document.getElementById('co').onclick=()=>ps.forEach(d=>d.open=false);
"""
def paper_html(r):
    s=r['summary']; hl=notes_of(r) if (not a.export or a.with_notes) else []
    doi=r.get('doi'); 
    meta=[]
    if doi: meta.append(f'DOI <a href="https://doi.org/{E(doi)}">{E(doi)}</a>'+(' <small>(unverified)</small>' if r.get('doi_status')=='unverified' else ''))
    j=r.get('journal') or r.get('venue_abbr'); jv=' '.join(x for x in [str(r['volume']) if r.get('volume') else '', f"({r['issue']})" if r.get('issue') else ''] if x)
    meta.append(f'Journal: {E(j)} {E(jv)}'.strip()+('' if r.get('journal') else ' <small>(abbr.)</small>'))
    if r.get('pages'): meta.append(f"{r['pages']} pp")
    path=f"<code>{E(r['path'])}</code>" if a.export else f'<a href="../{E(r["path"]).replace(" ","%20")}"><code>{E(r["path"])}</code></a>'
    kf=''.join(f'<li>{E(x)}</li>' for x in s['key_findings']) if s['key_findings'] else '<span class="pending">pending - top 3 key findings (with page refs)</span>'
    um=E(s['unique_method']) if s['unique_method'] else '<span class="pending">none recorded</span>'
    ver='verified' if s.get('verified') else 'unverified'
    hh=''
    if hl:
        by=collections.defaultdict(list)
        for h in hl: by[h['color']].append(h)
        for cid,items in by.items():
            c=colors.get(cid,{'hex':'#999','name':cid})
            hh+=f'<details class="sec"><summary><span class="dot" style="background:{c["hex"]}"></span>{E(c["name"])} ({len(items)})</summary>'
            for h in items: hh+=f'<div class="hl" style="--c:{c["hex"]}"><q>{E(h.get("quote"))}</q><div>{E(h.get("comment"))}</div><small>p.{E(h.get("page"))} · {E(h.get("source"))} · {E(h.get("added"))}</small></div>'
            hh+='</details>'
    else: hh='<span class="pending">no highlights yet</span>'
    return f'''<details class="paper" id="{r['id']}" data-status="{E(s['status'])}"><summary><span class="au">{E(r['first_author'])} {E(r['year'] or 'n.d.')}</span><span class="ti">{E(r['title'])}</span><span class="badges"><span class="pill">{E(r.get('venue_abbr') or '-')}</span><span class="pill">{E(r['kind'])}</span><span class="pill">summary: {E(s['status'])}, {ver}</span>{"".join(f'<span class="pill">{E(c)}</span>' for c in r.get('collections',[]))}</span></summary>
<div class="body"><div class="meta">{' · '.join(meta)}<br>{path}</div>
<details class="sec"><summary>Summary</summary><ol>{kf}</ol><p><b>Unique methodology:</b> {um}</p></details>
<details class="sec"><summary>Highlights ({len(hl)})</summary>{hh}</details></div></details>'''
idx=[]
for slug,pg in pages.items():
    rs=sorted(pg['recs'],key=lambda r:((r['first_author'] or '').lower(),r['year'] or 0))
    done=sum(1 for r in rs if r['summary']['status']!='pending')
    body=''.join(paper_html(r) for r in rs)
    open(f'{a.out}/{slug}.html','w',encoding='utf-8').write(f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{E(pg['title'])}</title><style>{CSS}</style>
<body><h1>{E(pg['title'])}</h1><div class="sub">{len(rs)} papers · {done} summarised · <a href="index.html">all categories</a></div>
<div class="bar"><input id="q" placeholder="filter this page..."><label><input type="checkbox" id="pend"> pending only</label><button id="ex">expand all</button><button id="co">collapse all</button></div>{body}<script>{JS}</script></body></html>''')
    idx.append((slug,pg['title'],len(rs),done))
idx.sort(key=lambda x:x[1].lower())
li=''.join(f'<li><a href="{s}.html">{E(t)}</a> <span class="pill">{n} papers</span> <span class="pill">{d} summarised</span></li>' for s,t,n,d in idx)
open(f'{a.out}/index.html','w',encoding='utf-8').write(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{E(os.path.basename(ROOT))} · library</title><style>{CSS}</style><body><h1>{E(os.path.basename(ROOT))}</h1><div class="sub">{len(recs)} papers · generated {datetime.date.today()}</div><ul class="idx">{li}</ul></body></html>')
print(f'{len(idx)} pages, {len(recs)} papers -> {a.out}')
