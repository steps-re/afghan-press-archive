import json,collections,re
o=json.load(open("heads.json")); P={x["page"]:x for x in o}
its=json.load(open("issues_fit.json"))
moved=0
for k,it in enumerate(its):
    lo=its[k-1]["start"]+1 if k else 1
    hi=its[k+1]["end"] if k+1<len(its) else o[-1]["page"]
    est=[x["page"]-x["pin"]+1 for x in o if x["no"]==it["no"] and x["pin"] and it["start"]-12<=x["page"]<=it["start"]+30]
    est=[e for e in est if lo<=e<=hi and abs(e-it["start"])<=12]
    c=collections.Counter(est).most_common(1)
    if c and (c[0][1]>=2 or abs(c[0][0]-it["start"])<=4) and c[0][0]!=it["start"]:
        it["start_fit"]=it["start"]; it["start"]=c[0][0]; moved+=1
    it["start_votes"]=c[0][1] if c else 0
# A contents cover (فهرست مندرجات) or a printed page 1 just before the start belongs to this
# issue, as long as no page in between names a different issue.
for k,it in enumerate(its):
    floor=its[k-1]["start"]+1 if k else 1
    p=it["start"]-1
    while p>=floor and it["start"]-p<=8:
        x=P[p]
        if x["no"] is not None and x["no"]!=it["no"]: break
        if x["cover"] or x["pin"]==1: it["start"]=p
        p-=1
# Pages before the first issue's masthead (adl0616: title page and front matter, 1-9) belong
# to no issue. The fit labels them issue 1; leave them out rather than mislabel them.
# A printed "page 1" (or a contents cover) within a few pages of the start is the strongest
# evidence there is; it overrides votes, which a single missing scan page shifts by one.
for k,it in enumerate(its):
    floor=its[k-1]["start"]+1 if k else 1
    ceil_=its[k+1]["start"]-1 if k+1<len(its) else o[-1]["page"]
    cands=[p for p in range(max(floor,it["start"]-8),min(ceil_,it["start"]+3)+1)
           if (P[p]["pin"]==1 or P[p]["cover"]) and P[p]["no"] in (None,it["no"])]
    if cands:
        best=min(cands,key=lambda p:abs(p-it["start"]))
        # a cover right before a page 1 is the issue's true first page
        if best-1>=floor and P[best-1]["cover"] and P[best-1]["no"] in (None,it["no"]): best-=1
        it["start"]=best
for a,b in zip(its,its[1:]+[None]): a["end"]=(b["start"]-1) if b else o[-1]["page"]
bad=[(a["year"],a["no"]) for a,b in zip(its,its[1:]) if b["start"]<=a["start"]]
print("moved",moved,"order violations",bad)
# masthead check: does the start page look like a front page?
front=lambda t: bool(re.search(r"فهرست|نگران|قیمت|سراج الاخبار",t[:200]))
print("start pages that look like a front page:",sum(front(P[i["start"]]["head"]) for i in its),"/",len(its))
json.dump(its,open("issues.json","w"),ensure_ascii=False,indent=0)
for i in its:
    if not front(P[i["start"]]["head"]): print(i["year"],i["no"],i["start"],i.get("start_fit"),i["start_votes"],"|",P[i["start"]]["head"][:90].replace("\n"," / "))
