#!/usr/bin/env python3
"""paper-library-ingest engine: find new science PDFs in download/inbox folders, propose where they belong, file them after approval.
Deterministic steps live here; judgement (confirm plan, name new categories, fix metadata) is done by the agent + owner.
Subcommands (run in order; every step is re-runnable):
  detect                       list candidate inbox folders (browser/Zotero/Downloads/Documents)
  scan   [--inbox P ...] [--since YYYY-MM-DD | --all] [--budget SEC]     -> _meta/ingest/scan.json
  plan                         -> _meta/ingest/plan.json (proposed destination per file; new-category proposals)
  apply  [--mode copy|move] [--run] [--no-commit]                         DRY RUN unless --run: files approved items, catalog, html, git commit
  selftest                     leave-one-out check of the classifier on the existing library
Library root: --root DIR, else $INGEST_ROOT, else the parent of this script's folder (when installed as <library>/tools/).
Exit codes: 0 ok; 2 usage / not a library / missing prerequisite step; 3 needs attention (unresolved or unapproved items, errors); 4 verification failure (copy not identical).
Streams: results on stdout, problems on stderr."""
import os,sys,re,json,math,hashlib,subprocess,shutil,time,argparse,collections,datetime,unicodedata,glob
def _root():
    for i,x in enumerate(sys.argv):
        if x=='--root' and i+1<len(sys.argv): return sys.argv[i+1]
        if x.startswith('--root='): return x[7:]
    return os.environ.get('INGEST_ROOT') or os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
ROOT=os.path.abspath(os.path.expanduser(_root()))
def die(msg,code=2):
    print(msg,file=sys.stderr); sys.exit(code)
META=f'{ROOT}/_meta'; ING=f'{META}/ingest'; PARENT=os.path.dirname(ROOT)
T_HIGH,T_MID,MARGIN=0.22,0.10,0.03      # calibrated on page-1 text (60 papers): folder-exact ~55-60%, top-level group 88-100%. NEVER auto-file: the user approves every item
MIN_BYTES=int(os.environ.get('INGEST_MIN_BYTES',20000)); MAX_DEPTH=3
EXCLUDE_DIRS={'.git','node_modules','Library','__pycache__','_to_delete','.Trash','site','export'}
STOP=set('the and for with from that this are was were has have not but its into their than then also which these those using use used can may our via over under between within among after before during about such been being each other more most some any all new two one three based study analysis data method methods approach results show shows high large single human mouse cells cell'.split())
def J(p,d=None):
    return json.load(open(p,encoding='utf-8')) if os.path.exists(p) else d
def W(p,o):
    os.makedirs(os.path.dirname(p),exist_ok=True); t=p+'.tmp'; json.dump(o,open(t,'w',encoding='utf-8'),indent=1,ensure_ascii=False); os.replace(t,p)
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for c in iter(lambda:f.read(1<<20),b''): h.update(c)
    return h.hexdigest()
CFG=J(f'{ING}/config.json',{})   # per-library settings: collections, new_category_parents, exclude_dirs
EXCLUDE_DIRS|=set(CFG.get('exclude_dirs',[]))
def run(cmd,t=20):
    try: return subprocess.run(cmd,capture_output=True,text=True,timeout=t).stdout
    except Exception: return ''
def records(): return [json.loads(l) for l in open(f'{META}/papers.jsonl',encoding='utf-8')] if os.path.exists(f'{META}/papers.jsonl') else []
def tok(t): return [w for w in re.findall(r"[a-z][a-z0-9\-]{2,}",t.lower()) if w not in STOP]
# ---------- detect ----------
def candidate_inboxes():
    H=os.path.expanduser('~'); c=[]
    for p in [f'{H}/Downloads',f'{H}/Desktop',f'{H}/Documents',f'{H}/Zotero/storage']: c.append((p,'standard'))
    for p in glob.glob(f'{H}/mnt/*'): c.append((p,'mounted'))
    for pf in glob.glob(f'{H}/Library/Application Support/Google/Chrome/*/Preferences')+glob.glob(f'{H}/.config/*/*/Preferences'):
        d=(J(pf,{}) or {}).get('download',{}).get('default_directory')
        if d: c.append((d,'browser-pref:'+pf))
    for pf in glob.glob(f'{H}/Library/Application Support/Firefox/Profiles/*/prefs.js'):
        m=re.search(r'browser\.download\.dir",\s*"([^"]+)"',open(pf,errors='ignore').read())
        if m: c.append((m.group(1),'firefox-pref'))
    if sys.platform=='darwin':
        d=run(['defaults','read','com.apple.Safari','DownloadsPath']).strip()
        if d: c.append((os.path.expanduser(d),'safari-pref'))
    seen=set();out=[]
    for p,why in c:
        p=os.path.realpath(p)
        if p in seen or not os.path.isdir(p) or p.startswith(PARENT) or p==ROOT: continue
        seen.add(p); out.append((p,why))
    return out
def cmd_detect(a):
    print('Candidate inbox folders (existing, readable):')
    for p,why in candidate_inboxes():
        n=sum(1 for dp,dn,fn in os.walk(p) for f in fn if f.lower().endswith('.pdf') and dp[len(p):].count(os.sep)<MAX_DEPTH)
        print(f'  {p}   [{why}]   pdfs(<=depth {MAX_DEPTH}): {n}')
    print('If a browser download folder is missing, this shell cannot see it: ask the owner to grant/mount it.')
# ---------- extraction ----------
def pdf_info(p):
    o=run(['pdfinfo',p]); g=lambda k:(re.search(rf'^{k}:\s*(.*)$',o,re.M) or [None,''])[1].strip()
    pg=g('Pages'); return dict(pages=int(pg) if pg.isdigit() else None,pdftitle=g('Title'))
def pdf_text(p,n=2): return run(['pdftotext','-q','-f','1','-l',str(n),p,'-'],30)
NONPAPER=re.compile(r'\b(invoice|rechnung|kontoauszug|steuer\w*|bescheid|versicherung\w*|lebenslauf|curriculum vitae|resume|boarding pass|bewerbung|anschreiben|cover letter|10-k|10-q|form 144|proxy statement|prospectus|annual report|earnings call|term sheet|payslip|gehaltsabrechnung|mietvertrag|receipt|quittung|e-?ticket|bank statement|tax return)\b',re.I)
SIG=[r'10\.\d{4,9}/\S+',r'\babstract\b',r'\bintroduction\b',r'\breferences\b',r'\bkey ?words?\b',r'et al\.',r'\b(nature|science|cell|biorxiv|medrxiv|pnas|elsevier|springer|wiley|oxford university press|genome|journal of|plos|frontiers|bmc|lancet|nejm|embo|acm|ieee|arxiv)\b',r'\b(received|accepted|published)\b']
def paper_verdict(name,text,pages):
    mm=NONPAPER.search(name) or NONPAPER.search(text[:1500])
    if mm: return 'not_paper','matches non-science pattern: '+mm.group(0)
    s=sum(1 for r in SIG if re.search(r,text,re.I))
    if len(text)<400: return 'borderline','little extractable text (scanned? slide? image-only)'
    if s>=3 and (pages or 0)>=4: return 'paper',f'{s}/8 paper signals'
    if s>=2: return 'borderline',f'only {s}/8 paper signals or very short ({pages} pp)'
    return ('not_paper' if (pages or 0)<4 else 'borderline'),f'{s}/8 paper signals ({pages} pp)'
DOI_RE=re.compile(r'10\.\d{4,9}/[^\s"<>\]\)]+')
VENUE=[('10.1126/sciadv','SciAdv'),('10.1126/science','Science'),('10.1016/j.cell','Cell'),('10.1073','PNAS'),('10.1101','bioRxiv'),('10.1093/nar','NAR'),('10.1093/bioinformatics','Bioinformatics'),('10.1186/s13059','GenomeBiol'),('10.1038/s41592','NatMethods'),('10.1038/s41587','NatBiotech'),('10.1038/s41588','NatGenet'),('10.1038/s41586','Nature'),('10.1038/s41467','NatCommun'),('10.1038/s41591','NatMed'),('10.1038/s41576','NatRevGenet'),('10.1164','AJRCCM'),('10.1183','ERJ'),('10.1161','Circulation'),('10.7554','eLife'),('10.1371','PLOS'),('10.1002','Wiley'),('10.1016','Elsevier'),('10.1038','Nature-family'),('10.1007','Springer'),('10.3389','Frontiers')]
def guess_meta(path,text,pdftitle):
    fn=os.path.basename(path)[:-4]; m={}
    d=DOI_RE.search(text); m['doi']=d.group(0).rstrip('.,;)') if d else None
    m['venue_abbr']=next((v for pre,v in VENUE if m['doi'] and m['doi'].lower().startswith(pre)),None)
    y=re.search(r'(?<!\d)(19[89]\d|20[0-3]\d)(?!\d)',fn)
    if y: m['year']=int(y.group(1))
    else:
        ys=collections.Counter(re.findall(r'(?:published|received|accepted|©|copyright)[^\n]{0,40}?((?:19|20)\d\d)',text,re.I)).most_common(1)
        m['year']=int(ys[0][0]) if ys else None
    au=None
    mm=re.match(r'^([A-Z][A-Za-z\-]+) et al\.? - ',fn) or re.match(r'^([A-Z][a-z]+)-[A-Z]',fn) or re.match(r'^([A-Z][A-Za-z\-]+)_(?:\d{4}|nd)_',fn)
    if mm: au=mm.group(1)
    lines=[l.strip() for l in text.split('\n') if l.strip()]
    bad=re.compile(r'doi|http|www\.|received|accepted|©|copyright|issn|vol\.|^\d+$|research article|original article|open access|preprint|biorxiv|medrxiv|downloaded from|supplementary|^article$',re.I)
    cand=[(i,l) for i,l in enumerate(lines[:25]) if 25<=len(l)<=250 and not bad.search(l)]
    title=None
    if pdftitle and len(pdftitle)>=15 and not re.search(r'untitled|microsoft|\.pdf|\.docx?|\.indd|\.tex',pdftitle,re.I): title=pdftitle
    elif cand:
        i,t=cand[0]
        if i+1<len(lines) and (i+1) in [c[0] for c in cand] and (lines[i+1][0].islower() or re.search(r'(:|-|\b(of|and|in|the|for|with|by|to|a|an|on))$',t)): t=t+' '+lines[i+1]; i+=1
        title=t
        if not au:
            for l in lines[i+1:i+8]:
                if len(l)<220 and (l.count(',')>=1 or ' and ' in l) and re.match(r'^[A-Z]',l) and not bad.search(l):
                    first=re.split(r',| and ',l)[0].strip(); w=re.sub(r'[\d\*†‡§¶]+','',first).split()
                    if 1<=len(w)<=4: au=w[-1]; break
    if not title: title=re.sub(r'[-_]+',' ',fn)
    m['title']=re.sub(r'\s+',' ',title).strip(); m['first_author']=au or 'Unknown'
    m['meta_confidence']='medium' if (au and pdftitle) else 'low'
    return m
def short_title(t):
    t=unicodedata.normalize('NFKD',t).encode('ascii','ignore').decode(); out=[];n=0
    for x in re.findall(r'[A-Za-z0-9]+',t):
        if n+len(x)>60 or len(out)>=8: break
        out.append(x); n+=len(x)+1
    return '-'.join(out) or 'Untitled'
def build_name(it):
    f=lambda s:re.sub(r'[^A-Za-z0-9\-]','',unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().replace(' ','-')) or 'Unknown'
    return f"{f(it.get('first_author') or 'Unknown')}_{it.get('year') or 'nd'}_{f(it.get('venue_abbr') or 'Unknown')}_{short_title(it['title'])}.pdf"
# ---------- classifier ----------
def folder_of(r): return os.path.dirname(r['path'])
def build_profiles(recs):
    prof=collections.defaultdict(collections.Counter)
    for r in recs:
        if r['kind']=='own_work': continue
        prof[folder_of(r)].update(tok(r['title']))
    return prof
def idf_of(prof):
    df=collections.Counter(w for c in prof.values() for w in c); N=len(prof)
    return {w:math.log((N+1)/(d+1))+1 for w,d in df.items()}
def vec(counter,idf):
    v={w:(1+math.log(c))*idf.get(w,1.0) for w,c in counter.items() if c>0}; n=math.sqrt(sum(x*x for x in v.values())) or 1
    return {w:x/n for w,x in v.items()}
def classify(text,prof,idf,only=None):
    q=vec(collections.Counter(tok(text)),idf); out=[]
    for f,c in prof.items():
        if only and not f.startswith(only): continue
        pv=vec(c,idf); out.append((f,sum(q[w]*pv[w] for w in q if w in pv)))
    return sorted(out,key=lambda x:-x[1])[:3]
def collection_rules(): return [(c['path'],re.compile(c['pattern'],re.I),c.get('min_hits',2)) for c in CFG.get('collections',[])]
def parents_of(recs):
    if CFG.get('new_category_parents'): return CFG['new_category_parents']
    colls={c['path'].split('/')[0] for c in CFG.get('collections',[])}
    return sorted({folder_of(r).split('/')[0] for r in recs if folder_of(r) and not folder_of(r).startswith('_') and folder_of(r).split('/')[0] not in colls and r['kind']!='own_work'})
def decide(text,title,prof,idf):
    """returns (dest, confidence, why, top3); confidence: high|suggest|none"""
    blob=title+' '+text[:3000]; hits={p:(len(rx.findall(blob))+2*len(rx.findall(title)),mh) for p,rx,mh in collection_rules()}
    ok=[p for p,(h,mh) in hits.items() if h>=mh]; coll=ok[0] if len(ok)==1 else None
    if coll:
        top=classify(title+' '+text[:2500],prof,idf,only=coll)
        return (top[0][0] if top else coll),'suggest',f'collection rule ({coll.split("/")[-1]} terms x{hits[coll][0]}); a configured collection wins over topical folders',top
    top=classify(title+' '+title+' '+text[:2500],prof,idf)
    if not top: return None,'none','empty profile (no papers in library yet)',[]
    s1=top[0][1]; s2=top[1][1] if len(top)>1 else 0
    if s1>=T_HIGH and s1-s2>=MARGIN: return top[0][0],'high',f'score {s1:.2f}, margin {s1-s2:.2f}',top
    if s1>=T_MID: return top[0][0],'suggest',f'score {s1:.2f} (low margin or mid score) - confirm',top
    return None,'none',f'best score {s1:.2f} < {T_MID}',top
def cmd_selftest(a):
    recs=[r for r in records() if r['kind']=='paper' and not r['path'].startswith('5_Own')]; prof=build_profiles(recs); idf=idf_of(prof)
    bands=collections.defaultdict(lambda:[0,0]); t1=t3=g1=0
    for r in recs:
        f=folder_of(r); toks=collections.Counter(tok(r['title'])); prof[f].subtract(toks)
        top=classify(r['title']+' '+r['title'],prof,idf); prof[f].update(toks)
        if not top: continue
        ok=top[0][0]==f; t1+=ok; t3+=any(x[0]==f for x in top); g1+=top[0][0].split('/')[0]==f.split('/')[0]
        s=top[0][1]; b='high' if s>=T_HIGH else ('mid' if s>=T_MID else 'low'); bands[b][0]+=1; bands[b][1]+=ok
    n=len(recs); print(f'papers={n}  folder top1={t1/n:.0%}  top3={t3/n:.0%}  top-level-group top1={g1/n:.0%}')
    for b,(c,k) in sorted(bands.items()): print(f'  band {b:>5}: n={c:4d} folder-correct={k/max(c,1):.0%}')
    print('(title-only. Real runs also use page-1 text. Disease-collection papers compete with topical folders by design.)')
# ---------- scan ----------
def walk(inbox):
    for dp,dn,fn in os.walk(inbox):
        dn[:]=[d for d in dn if d not in EXCLUDE_DIRS and not d.startswith('.') and not os.path.realpath(os.path.join(dp,d)).startswith(PARENT)]
        if dp[len(inbox):].count(os.sep)>=MAX_DEPTH: dn[:]=[]
        for f in fn:
            if f.lower().endswith('.pdf') and not f.startswith('.'): yield os.path.join(dp,f)
def default_inboxes():
    return [p for p,w in candidate_inboxes() if os.path.basename(p) in ('Downloads','Documents','Desktop','Zotero','storage') or w.split(':')[0] in ('browser-pref','firefox-pref','safari-pref')]
def cmd_scan(a):
    os.makedirs(ING,exist_ok=True); state=J(f'{ING}/state.json',{}); ign=set(J(f'{ING}/ignore.json',[])); cache=J(f'{ING}/seen.json',{})
    known={r['sha256']:r['path'] for r in records()}
    inboxes=[os.path.realpath(os.path.expanduser(p)) for p in a.inbox] if a.inbox else default_inboxes()
    if a.all: since=0
    elif a.since: since=datetime.datetime.fromisoformat(a.since).timestamp()
    elif state.get('last_scan'): since=datetime.datetime.fromisoformat(state['last_scan']).timestamp()
    else: die('No previous scan recorded: pass --since YYYY-MM-DD or --all.')
    t0=time.time(); started=datetime.datetime.now().isoformat(timespec='seconds'); items=[]; left=0; batch={}
    for ib in inboxes:
        for p in walk(ib):
            try: st=os.stat(p)
            except OSError: continue
            if st.st_mtime<since or st.st_size<MIN_BYTES: continue
            key=f'{p}|{st.st_size}|{int(st.st_mtime)}'; c=cache.get(key)
            if c is None:
                if time.time()-t0>a.budget: left+=1; continue
                h=sha(p); c=dict(sha=h)
                if h not in known and h not in ign:
                    c.update(pdf_info(p)); c['text']=pdf_text(p)[:3500]
                cache[key]=c
            h=c['sha']; it=dict(src=p,sha=h,id='p_'+h[:12],bytes=st.st_size,mtime=datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec='minutes'))
            if h in known: it.update(status='skip',reason=f'already in library: {known[h]}')
            elif h in ign: it.update(status='skip',reason='on ignore list')
            elif h in batch: it.update(status='skip',reason=f'identical to {batch[h]}')
            else:
                batch[h]=p; v,why=paper_verdict(os.path.basename(p),c.get('text',''),c.get('pages')); it.update(status=v,reason=why,pages=c.get('pages'),pdftitle=c.get('pdftitle'),text=c.get('text',''))
            items.append(it)
    json.dump(cache,open(f'{ING}/seen.json','w'))
    W(f'{ING}/scan.json',dict(started=started,since=datetime.datetime.fromtimestamp(since).isoformat(timespec='minutes'),inboxes=inboxes,incomplete_files_left=left,items=items))
    print('inboxes:',*inboxes,sep='\n  '); print('found:',dict(collections.Counter(i['status'] for i in items)))
    print(f'INCOMPLETE: {left} files not yet read (time budget). Run scan again to continue.' if left else 'scan complete -> _meta/ingest/scan.json')
# ---------- plan ----------
def norm_title(t): return set(tok(t))
def cluster(nomatch,recs,idf):
    """single-link clustering of unmatched papers by batch tf-idf cosine; returns list of new-category proposals"""
    docs=[collections.Counter(tok(i['title']+' '+i['title']+' '+i['page1_text'])) for i in nomatch]; df=collections.Counter(w for d in docs for w in d)
    bi={w:math.log((len(docs)+1)/(c+0.5))+1 for w,c in df.items()}; V=[vec(d,bi) for d in docs]; par=list(range(len(docs)))
    def f(x):
        while par[x]!=x: par[x]=par[par[x]]; x=par[x]
        return x
    for i in range(len(docs)):
        for j in range(i+1,len(docs)):
            if sum(V[i][w]*V[j][w] for w in V[i] if w in V[j])>=0.15: par[f(i)]=f(j)
    groups=collections.defaultdict(list)
    for i in range(len(docs)): groups[f(i)].append(i)
    par=parents_of(recs); prof={k:v for k,v in build_profiles(recs).items() if k.split('/')[0] in par}; out=[]
    for g in groups.values():
        if len(g)<2: continue
        agg=collections.Counter(); [agg.update(docs[i]) for i in g]
        name='_'.join(w.capitalize() for w,_ in sorted(((w,c*bi[w]) for w,c in agg.items()),key=lambda x:-x[1])[:3])
        tops=classify(' '.join(nomatch[i]['title'] for i in g),prof,idf); parent=tops[0][0].split('/')[0] if tops else (par[0] if par else 'Uncategorized')
        path=f'{parent}/{name}'; out.append(dict(path=path,approved=False,parents=par,members=[nomatch[i]['id'] for i in g],note='AGENT: pick a sensible name + parent (from `parents`), ask the owner, then set approved:true and update members dest'))
        for i in g: nomatch[i].update(alt_dest=nomatch[i].get('dest'),dest=path,reason=f'cluster of {len(g)} unmatched papers -> proposed new category')
    return out
def cmd_plan(a):
    sc=J(f'{ING}/scan.json')
    if not sc: die('run scan first')
    if sc['incomplete_files_left']: print('WARNING: scan was incomplete; the plan covers only what was read.')
    recs=records(); prof=build_profiles(recs); idf=idf_of(prof); libtitles=[(r['path'],norm_title(r['title']),(r.get('doi') or '').lower()) for r in recs]
    items=[];skipped=[];nomatch=[]
    for s in sc['items']:
        if s['status']=='skip': skipped.append(dict(src=s['src'],reason=s['reason'])); continue
        m=guess_meta(s['src'],s['text'],s.get('pdftitle')); it=dict(src=s['src'],sha=s['sha'],id=s['id'],pages=s.get('pages'),bytes=s['bytes'],**m); it['page1_text']=s['text'][:1200]
        if s['status']=='not_paper': it.update(action='skip',reason='probably not a paper: '+s['reason'],dest=None,confidence='none'); items.append(it); continue
        dest,conf,why,top=decide(s['text'],m['title'],prof,idf); it.update(dest=dest,confidence=conf,why=why,top3=[(f,round(x,2)) for f,x in top])
        nt=norm_title(m['title']); dup=None
        for p,t,d in libtitles:
            if (m['doi'] and d and d==m['doi'].lower()) or (len(nt)>=4 and len(nt&t)/max(len(nt|t),1)>=0.8): dup=p; break
        if dup: it.update(action='ask',reason=f'possible duplicate/other version of {dup}; keep both only if preprint vs published',dest=None)
        elif s['status']=='borderline' and (conf=='none' or (top and top[0][1]<0.15)): it.update(action='skip',dest=None,reason='low paper signals and no topical match: '+s['reason'])
        elif s['status']=='borderline': it.update(action='ask',reason='borderline (manual/slides/scan?): '+s['reason'])
        elif conf=='high': it.update(action='file',approved=False,reason='likely: '+why)
        elif conf=='suggest': it.update(action='ask',reason='confirm suggested folder: '+why); (nomatch.append(it) if top and top[0][1]<0.14 and 'collection rule' not in why else None)
        else: it.update(action='ask',reason='no matching category: '+why); nomatch.append(it)
        items.append(it)
    newcats=cluster(nomatch,recs,idf) if len(nomatch)>=2 else []
    W(f'{ING}/plan.json',dict(created=datetime.datetime.now().isoformat(timespec='seconds'),scan_started=sc['started'],existing_folders=sorted(prof),new_categories=newcats,items=items,skipped=skipped))
    print('plan items:',dict(collections.Counter(i['action'] for i in items)),'| auto-skipped (known/duplicate):',len(skipped),'| new-category proposals:',len(newcats))
    print('-> _meta/ingest/plan.json. Show it to the owner; edit action/dest/metadata; approve new categories; then run apply.')
# ---------- apply ----------
def cmd_apply(a):
    pl=J(f'{ING}/plan.json')
    if not pl: die('no plan: run plan first')
    approved={c['path'] for c in pl['new_categories'] if c.get('approved')}; done=[];errs=[];made=[];pending=0
    meta=J(f'{META}/ingest_meta.json',{}); ign=set(J(f'{ING}/ignore.json',[]))
    for it in pl['items']:
        act=it.get('action')
        if act=='ignore': ign.add(it['sha']); continue
        if act=='ask' or (act=='file' and not it.get('approved')): pending+=1; continue
        if act!='file': continue
        d=it.get('dest')
        if not d or d.startswith('/') or '..' in d.split('/'): errs.append((it['src'],'bad dest')); continue
        full=f'{ROOT}/{d}'
        if not os.path.isdir(full) and d not in approved: errs.append((it['src'],f'category {d} not approved')); continue
        name=it.get('filename_override') or build_name(it); tgt=f'{full}/{name}'
        if os.path.exists(tgt) and sha(tgt)!=it['sha']: tgt=tgt[:-4]+'_2.pdf'
        if not a.run: print(f"[dry] {it['src']}\n   -> {d}/{os.path.basename(tgt)}"); continue
        if not os.path.isdir(full): os.makedirs(full); made.append(d)
        if not os.path.exists(tgt):
            tmp=tgt+'.part'; shutil.copy2(it['src'],tmp)
            if sha(tmp)!=it['sha']: os.remove(tmp); errs.append((it['src'],'copy verify failed')); continue
            os.replace(tmp,tgt)
        if sha(tgt)!=it['sha']: errs.append((it['src'],'target differs')); continue
        meta[it['id']]=dict(title=it['title'],first_author=it.get('first_author'),year=it.get('year'),venue_abbr=it.get('venue_abbr'),doi=it.get('doi'),meta_source='ingest:'+it.get('meta_confidence','low'))
        note=''
        if a.mode=='move':
            try: os.remove(it['src'])
            except OSError:
                q=os.path.join(os.path.dirname(it['src']),'_to_delete'); os.makedirs(q,exist_ok=True); shutil.move(it['src'],os.path.join(q,os.path.basename(it['src']))); note=' (source moved to _to_delete/: deletion not permitted)'
        done.append((it['src'],f'{d}/{os.path.basename(tgt)}'+note))
    if not a.run:
        print('DRY RUN (nothing written). problems:',errs,'| unresolved/unapproved:',pending,'| re-run with --run to apply'); sys.exit(3 if (errs or pending) else 0)
    W(f'{META}/ingest_meta.json',meta); W(f'{ING}/ignore.json',sorted(ign))
    with open(f'{ING}/log.jsonl','a') as f: f.write(json.dumps(dict(when=datetime.datetime.now().isoformat(timespec='seconds'),mode=a.mode,filed=done,new_categories=made,errors=errs,left_unresolved=pending))+'\n')
    if not pending and not errs: st=J(f'{ING}/state.json',{}); st['last_scan']=pl['scan_started']; W(f'{ING}/state.json',st)
    print(f'filed {len(done)}, new categories {made}, errors {len(errs)}, unresolved(ask) {pending}')
    for s,d in done: print('  +',d)
    for e in errs: print('  !',e)
    rc=4 if any('verify' in e[1] or 'differs' in e[1] for e in errs) else (3 if (errs or pending) else 0)
    if not done: sys.exit(rc)
    if a.no_commit: print('commit skipped; run: tools/commit.sh "ingest ..."'); sys.exit(rc)
    r=subprocess.run(['bash',f'{ROOT}/tools/commit.sh',f'ingest {len(done)} papers'+(f' (+{len(made)} new categories)' if made else '')],capture_output=True,text=True); print(r.stdout.strip(),r.stderr.strip()[-300:]); sys.exit(rc if r.returncode==0 else 4)
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('--root',help='library root (folder containing _meta/papers.jsonl)'); sp=ap.add_subparsers(dest='cmd',required=True)
    sp.add_parser('detect'); sp.add_parser('plan'); sp.add_parser('selftest')
    s=sp.add_parser('scan'); s.add_argument('--inbox',action='append'); s.add_argument('--since'); s.add_argument('--all',action='store_true'); s.add_argument('--budget',type=int,default=120)
    s=sp.add_parser('apply'); s.add_argument('--mode',choices=['copy','move'],default='copy'); s.add_argument('--no-commit',action='store_true'); s.add_argument('--run',action='store_true',help='actually write; without it apply is a dry run')
    a=ap.parse_args()
    if not os.path.exists(f'{META}/papers.jsonl'): die(f'{ROOT} is not a library (no _meta/papers.jsonl). Pass --root DIR or create one with init_library.py')
    globals()['cmd_'+a.cmd](a)
