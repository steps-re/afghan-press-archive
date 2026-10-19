import json,re,sys
D=str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩","01234567890123456789")
ORD={"اول":1,"یکم":1,"يكم":1,"دوم":2,"سوم":3,"چهارم":4,"پنجم":5,"ششم":6,"هفتم":7,"هشتم":8}
rows=[json.loads(l) for l in open("siraj.jsonl")]
out=[]
for r in rows:
    h=r["text"][:220].translate(D)
    # "ما بعد از نمبر ۱۴" (continued from no. 14) is an article cross-reference, not this page's issue
    h=re.sub(r"(?:ما\s*)?بعد\s*(?:از|ار)\s*(?:نمره|نمبر|شماره)\S*\s*\(?\s*\d{1,3}","",h)
    m=re.search(r"(?:نمره|نمبر|شمار)[هةۀٔ]*\s*[\(\)]?\s*\(?\s*(\d{1,3}|اول|دوم|سوم)",h)
    no=None
    if m: no=int(m.group(1)) if m.group(1).isdigit() else ORD.get(m.group(1))
    pm=re.search(r"(?:صفح|صحی?ف|صحيف)[هةۀ]?\S*\s*\(?\s*(\d{1,3})",h)
    ym=re.search(r"سال\s*(اول|یکم|يكم|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|\d)",h)
    yr=None
    if ym: yr=int(ym.group(1)) if ym.group(1).isdigit() else ORD.get(ym.group(1))
    out.append({"page":r["page"],"no":no,"pin":int(pm.group(1)) if pm else None,"year":yr,"head":r["text"][:160],"cover":bool(re.search(r"فهرست",h[:200]))})
json.dump(out,open("heads.json","w"),ensure_ascii=False)
n=len(out); print("issue no found",sum(o["no"] is not None for o in out),"/",n,"; page-in-issue",sum(o["pin"] is not None for o in out),"; year",sum(o["year"] is not None for o in out))
print("first pages (pin==1):",sum(o["pin"]==1 for o in out))
seq=[(o["page"],o["no"]) for o in out if o["no"]]
print(" ".join(f"{p}:{n}" for p,n in seq[::12]))
