"""Fit one non-decreasing (year, issue) label to every page, minimising disagreement with what
the running heads say. A misread digit on one page then costs 1 and cannot open a new issue."""
import json
o=json.load(open("heads.json"))
Y=range(1,8); N=range(1,31)
S=[(y,n) for y in Y for n in N]; K=len(S)
INF=10**9
def cost(x,s):
    c=0
    if x["no"] is not None and x["no"]!=s[1]: c+=1
    if x["year"] is not None and x["year"]!=s[0]: c+=1
    return c
n=len(o); dp=[[INF]*K for _ in range(n)]; bk=[[0]*K for _ in range(n)]
for k in range(K): dp[0][k]=cost(o[0],S[k])
for i in range(1,n):
    best,bi=INF,0
    for k in range(K):
        if dp[i-1][k]<best: best,bi=dp[i-1][k],k
        dp[i][k]=best+cost(o[i],S[k]); bk[i][k]=bi
k=min(range(K),key=lambda k:dp[-1][k]); lab=[None]*n
for i in range(n-1,-1,-1): lab[i]=S[k]; k=bk[i][k]
print("total disagreement", min(dp[-1]))
issues=[]
for i,x in enumerate(o):
    if i==0 or lab[i]!=lab[i-1]: issues.append({"year":lab[i][0],"no":lab[i][1],"start":x["page"]})
for a,b in zip(issues,issues[1:]+[None]): a["end"]=(b["start"]-1) if b else o[-1]["page"]
# support: pages inside the span whose own head agrees
for it in issues:
    span=[x for x in o if it["start"]<=x["page"]<=it["end"]]
    it["pages"]=len(span); it["support"]=sum(1 for x in span if x["no"]==it["no"])
json.dump(issues,open("issues_fit.json","w"),ensure_ascii=False,indent=0)
from collections import defaultdict
by=defaultdict(list)
for it in issues: by[it["year"]].append(it)
for y,its in by.items():
    nos=[i["no"] for i in its]; miss=[m for m in range(1,max(nos)+1) if m not in nos]
    print(f"year {y}: {len(its)} issues, pages {its[0]['start']}-{its[-1]['end']}, missing {miss}, weak {[ (i['no'],i['support'],i['pages']) for i in its if i['support']<2]}")
