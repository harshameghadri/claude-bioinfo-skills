#!/usr/bin/env python3
"""Rebuild _meta/papers.jsonl + _meta/catalog.csv from the PDFs on disk.
Idempotent. Preserves hand/LLM-filled fields (summary, journal, volume, issue, doi, ...).
Paper id = 'p_' + first 12 hex of the file's SHA-256 (stable across renames/moves).
Usage: catalog.py [--root DIR]   (prints a diff summary). Exit codes: 0 ok, 2 not a library.
Writes only <root>/_meta/papers.jsonl, catalog.csv, removed.jsonl, .sha_cache.json, notes/."""
import os,sys,json,csv,hashlib,re,subprocess,datetime,collections,argparse

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('--root',help='library root (default: parent of this script folder)'); args=ap.parse_args(argv)
    ROOT=os.path.abspath(os.path.expanduser(args.root or os.path.join(os.path.dirname(os.path.abspath(__file__)),'..'))); META=f'{ROOT}/_meta'
    if not os.path.isdir(META): print(f'{ROOT} is not a library (no _meta/). Pass --root DIR.',file=sys.stderr); return 2
    SKIP={'_meta','.git','site','export','tools','__pycache__'}
    TODAY=datetime.date.today().isoformat()
    def sha(p):
        h=hashlib.sha256()
        with open(p,'rb') as f:
            for c in iter(lambda:f.read(1<<20),b''): h.update(c)
        return h.hexdigest()
    def jl(p): return [json.loads(l) for l in open(p,encoding='utf-8')] if os.path.exists(p) else []
    cache_p=f'{META}/.sha_cache.json'; cache=json.load(open(cache_p)) if os.path.exists(cache_p) else {}
    files=[]
    for dp,dn,fn in os.walk(ROOT):
        dn[:]=[d for d in dn if d not in SKIP and not d.startswith('.')]
        for f in fn:
            if f.lower().endswith('.pdf'): files.append(os.path.relpath(os.path.join(dp,f),ROOT))
    old={r['id']:r for r in jl(f'{META}/papers.jsonl')}
    oldpath={i:r['path'] for i,r in old.items()}   # snapshot: records are updated in place below
    boot=json.load(open(f'{META}/legacy/bootstrap_meta.json')) if os.path.exists(f'{META}/legacy/bootstrap_meta.json') else {}
    ing=json.load(open(f'{META}/ingest_meta.json')) if os.path.exists(f'{META}/ingest_meta.json') else {}
    cfgp=f'{META}/ingest/config.json'; CFGC=json.load(open(cfgp)).get('collections',[]) if os.path.exists(cfgp) else []
    new={};warn=[]
    def kind_of(path):
        b=os.path.basename(path).lower()
        if path.startswith('5_Own_Work'): return 'own_work'
        if 'supplement' in b or 'supp' in b.split('_')[-1]: return 'supplement'
        if 'protocol' in b: return 'protocol'
        return 'paper'
    def parse_name(path):
        s=os.path.basename(path)[:-4]; p=s.split('_')
        if len(p)>=4 and re.fullmatch(r'\d{4}|nd',p[1]): return p[0],(int(p[1]) if p[1]!='nd' else None),p[2],'_'.join(p[3:]).replace('-',' ')
        return None,None,None,s.replace('-',' ').replace('_',' ')
    for rel in sorted(files):
        ab=os.path.join(ROOT,rel); st=os.stat(ab); key=f'{rel}|{st.st_size}|{int(st.st_mtime)}'
        if key in cache: h=cache[key]
        else: h=sha(ab); cache[key]=h
        pid='p_'+h[:12]
        if pid in new: warn.append(f'identical content on disk: {rel}  ==  {new[pid]["path"]}'); continue
        b=dict(boot.get(rel,{})); b.update({k:v for k,v in ing.get(pid,{}).items() if v is not None}); au,yr,ve,ti=parse_name(rel)
        r=old.get(pid)
        if r is None:
            pages=None
            try:
                out=subprocess.run(['pdfinfo',ab],capture_output=True,text=True,timeout=20).stdout
                m=re.search(r'Pages:\s+(\d+)',out); pages=int(m.group(1)) if m else None
            except Exception: pass
            doi=b.get('doi')
            r=dict(id=pid,sha256=h,title=b.get('title') or ti,title_source=('ingest' if str(b.get('meta_source','')).startswith('ingest') else 'manifest') if b.get('title') else 'filename',
              first_author=b.get('first_author') or au,year=b.get('year') or yr,venue_abbr=b.get('venue_abbr') or ve,
              doi=doi,doi_status='unverified' if doi else None,journal=None,volume=None,issue=None,pages=pages,
              summary=dict(status='pending',key_findings=[],unique_method=None,verified=False),extra_collections=b.get('extra_collections',[]),
              meta_source=b.get('meta_source','filename'),added=TODAY,bytes=st.st_size)
        r['path']=rel; r['topic']=os.path.dirname(rel); r['kind']=kind_of(rel)
        cols=set(r.get('extra_collections',[]))
        m=re.match(r'0_Disease_Collections/([^/]+)/',rel)
        if m: cols.add(m.group(1))
        for c_ in CFGC:
            if rel.startswith(c_['path']+'/'): cols.add(c_['path'].split('/')[-1])
        r['collections']=sorted(cols)
        new[pid]=r
    removed=[old[i] for i in old if i not in new]
    added=[i for i in new if i not in old]; moved=[i for i in new if i in oldpath and oldpath[i]!=new[i]['path']]
    os.makedirs(f'{META}/notes',exist_ok=True)
    with open(f'{META}/papers.jsonl','w',encoding='utf-8') as f:
        for r in sorted(new.values(),key=lambda r:r['path']): f.write(json.dumps(r,ensure_ascii=False)+'\n')
    if removed:
        with open(f'{META}/removed.jsonl','a',encoding='utf-8') as f:
            for r in removed: r['removed_on']=TODAY; f.write(json.dumps(r,ensure_ascii=False)+'\n')
    cols=['id','path','topic','collections','first_author','year','venue_abbr','journal','volume','issue','doi','doi_status','title','kind','pages','sha256','summary_status','summary_verified','n_highlights']
    with open(f'{META}/catalog.csv','w',newline='',encoding='utf-8') as f:
        w=csv.writer(f,lineterminator='\n'); w.writerow(cols)
        for r in sorted(new.values(),key=lambda r:r['path']):
            npth=f"{META}/notes/{r['id']}.json"; nh=len(json.load(open(npth)).get('highlights',[])) if os.path.exists(npth) else 0
            w.writerow([r['id'],r['path'],r['topic'],';'.join(r['collections']),r['first_author'],r['year'],r['venue_abbr'],r['journal'],r['volume'],r['issue'],r['doi'],r['doi_status'],r['title'],r['kind'],r['pages'],r['sha256'],r['summary']['status'],r['summary']['verified'],nh])
    json.dump(cache,open(cache_p,'w'))
    print(f'papers={len(new)} added={len(added)} removed={len(removed)} moved/renamed={len(moved)}')
    for w_ in warn: print('WARN',w_)
    return 0
if __name__ == "__main__":
    sys.exit(main())
