#!/usr/bin/env python3
"""Held-out accuracy of the ingest.py classifier on a labelled set of papers (offline; no model).
Usage: bench_classifier.py PAPERS_JSON [INGEST_PY]
PAPERS_JSON is a list of {"folder": "Parent/Name", "pmid": "...", "title": "...", "abstract": "..."}; the library profile is the titles of
the papers in a folder (exactly what the skill does) and the query is title + abstract, standing in for page-1 text. The data set used for
the published numbers is described by benchmark_pmids.tsv (PubMed ids and folders; fetch titles and abstracts from PubMed yourself).
Prints: leave-one-out accuracy, accuracy with 8/5/3/2/1 library papers per folder, and how papers of a topic absent from the library are labelled.
Exit codes: 0 ok, 2 usage."""
import os, sys, json, random, collections, importlib.util, tempfile
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
    print(__doc__); sys.exit(0 if len(sys.argv) > 1 else 2)
HERE = os.path.dirname(os.path.abspath(__file__)); papers_path = sys.argv[1]
ingest_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "scripts", "ingest.py")
tmp = tempfile.mkdtemp(); os.makedirs(f"{tmp}/_meta/ingest"); os.environ["INGEST_ROOT"] = tmp
spec = importlib.util.spec_from_file_location("ingest", ingest_path); I = importlib.util.module_from_spec(spec); sys.argv = [sys.argv[0]]; spec.loader.exec_module(I)
P = json.load(open(papers_path))
folders = sorted({p["folder"] for p in P}); by = collections.defaultdict(list)
for p in P: by[p["folder"]].append(p)

def recs_of(ps): return [dict(kind="paper", path=f'{p["folder"]}/x{p["pmid"]}.pdf', title=p["title"]) for p in ps]

def evaluate(profile_ps, test_ps):
    prof = I.build_profiles(recs_of(profile_ps)); idf = I.idf_of(prof)
    r = collections.Counter(); band = collections.defaultdict(lambda: [0, 0])
    for p in test_ps:
        dest, conf, why, top = I.decide(p["abstract"], p["title"], prof, idf)
        t1 = top[0][0] if top else None
        ok = t1 == p["folder"]; okg = bool(t1) and t1.split("/")[0] == p["folder"].split("/")[0]
        r["n"] += 1; r["top1"] += ok; r["top3"] += any(x[0] == p["folder"] for x in top); r["grp"] += okg
        band[conf][0] += 1; band[conf][1] += (dest == p["folder"])
    return r, band

def show(label, r, band):
    n = r["n"]; b = " ".join(f"{k}:n={v[0]},right={v[1]/max(v[0],1):.0%}" for k, v in sorted(band.items()))
    print(f"{label:34s} n={n:5d} folder@1={r['top1']/n:.0%} @3={r['top3']/n:.0%} group@1={r['grp']/n:.0%} | {b}")

print(f"folders={len(folders)} papers={len(P)} per-folder={sorted(collections.Counter(p['folder'] for p in P).values())[:3]}...")
# 1) leave-one-out, full library
tot = collections.Counter(); tb = collections.defaultdict(lambda: [0, 0])
for p in P:
    r, b = evaluate([q for q in P if q is not p], [p]); tot.update(r)
    for k, v in b.items(): tb[k][0] += v[0]; tb[k][1] += v[1]
show("LOO, library = all other papers", tot, tb)
# 2) smaller libraries: k seed papers per folder, test on the rest, 30 random draws
for k in (8, 5, 3, 2, 1):
    tot = collections.Counter(); tb = collections.defaultdict(lambda: [0, 0]); rnd = random.Random(7)
    for _ in range(30):
        prof_ps, test_ps = [], []
        for f in folders:
            ps = by[f][:]; rnd.shuffle(ps); prof_ps += ps[:k]; test_ps += ps[k:]
        r, b = evaluate(prof_ps, test_ps); tot.update(r)
        for kk, v in b.items(): tb[kk][0] += v[0]; tb[kk][1] += v[1]
    show(f"{k} papers per folder in library", tot, tb)
# 3) novel topic: whole folder removed from the library; any confident (high) verdict is a wrong confident verdict
print("\nnovel topic (folder absent from library): how are its papers labelled?")
for f in folders:
    prof_ps = [p for p in P if p["folder"] != f]; prof = I.build_profiles(recs_of(prof_ps)); idf = I.idf_of(prof)
    c = collections.Counter(I.decide(p["abstract"], p["title"], prof, idf)[1] for p in by[f])
    print(f"  {f:38s} high={c['high']:2d} suggest={c['suggest']:2d} none={c['none']:2d}")
