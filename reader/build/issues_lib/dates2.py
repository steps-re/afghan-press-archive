import json,subprocess,os
T={json.loads(l)["page"]:json.loads(l)["text"] for l in open("siraj.jsonl")}
its={f'{i["year"]}-{i["no"]}@{i["start"]}':i for i in json.load(open("issues.json"))}
need=json.load(open("need.json"))
# Vertex settings (VERTEX_PROJECT_ID, VERTEX_LOCATION, VERTEX_ACCOUNT) come from the environment.
env=dict(os.environ)
out=json.load(open("dates2.json")) if os.path.exists("dates2.json") else {}
PROMPT="""Below is the machine transcription of the first four pages held for one issue of the Kabul newspaper Siraj al-Akhbar (1911-1918). The masthead (often on the page headed صفحه/صحیفه ۱, sometimes after a contents page) prints the issue date in up to three calendars, e.g. "تاریخ قمری ... تاریخ شمسی ... تاریخ انگریزی ...". The large ۱۳۲۹ in the title logo is the founding year, NOT the issue date.
Return ONLY JSON, copying each date exactly as printed in the masthead, or null if that calendar is not printed there:
{"hijri": "...", "solar": "...", "gregorian": "...", "evidence": "<exact masthead words, max 20>"}
Ignore dates inside articles, news reports or letters.

TEXT:
"""
for k in need:
    if k in out: continue
    s=its[k]["start"]
    txt="\n=== next page ===\n".join(T.get(p,"")[:900] for p in range(s,s+4))
    try:
        r=subprocess.run(["llm","-m","vertex/gemini-3.8-flash","-o","temperature","0",PROMPT+txt],capture_output=True,text=True,env=env,stdin=subprocess.DEVNULL,timeout=90)
    except subprocess.TimeoutExpired:
        print("timeout",k,flush=True); continue
    t=r.stdout.strip().strip("`").removeprefix("json").strip()
    try: out[k]=json.loads(t)
    except Exception: out[k]={"error":(r.stdout+r.stderr)[:300]}
    json.dump(out,open("dates2.json","w"),ensure_ascii=False,indent=0)
print(len(out),"done")
