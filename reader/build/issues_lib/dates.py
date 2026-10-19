import json,subprocess,os,sys
T={json.loads(l)["page"]:json.loads(l)["text"] for l in open("siraj.jsonl")}
its=json.load(open("issues.json"))
# Vertex settings (VERTEX_PROJECT_ID, VERTEX_LOCATION, VERTEX_ACCOUNT) come from the environment.
env=dict(os.environ)
out=json.load(open("dates.json")) if os.path.exists("dates.json") else {}
PROMPT="""Below is the machine transcription of the first two pages held for one issue of the Kabul newspaper Siraj al-Akhbar (1911-1918). Find the issue's publication date as printed (usually in the masthead or heading). Return ONLY JSON:
{"hijri": "<day month year exactly as printed, Persian script, or null>", "gregorian": "<as printed, or null>", "hijri_iso": "<YYYY-MM-DD in the Hijri calendar if day, month and year are all printed, else null>", "issue_printed": "<issue number as printed, or null>", "evidence": "<the exact words you read the date from, max 15 words>"}
Do not compute or guess a date that is not printed. A date inside an article (a news report, a letter) is NOT the issue date; ignore it.

TEXT:
"""
for it in its:
    key=f'{it["year"]}-{it["no"]}@{it["start"]}'
    if key in out: continue
    txt=(T[it["start"]][:1500]+"\n---\n"+T.get(it["start"]+1,"")[:600])
    r=subprocess.run(["llm","-m","vertex/gemini-3.8-flash","-o","temperature","0",PROMPT+txt],capture_output=True,text=True,env=env,stdin=subprocess.DEVNULL,timeout=120)
    s=r.stdout.strip().strip("`").removeprefix("json").strip()
    try: out[key]=json.loads(s)
    except Exception: out[key]={"error":(r.stdout+r.stderr)[:300]}
    json.dump(out,open("dates.json","w"),ensure_ascii=False,indent=0)
print(len(out),"done;",sum(1 for v in out.values() if "error" in v),"errors;",sum(1 for v in out.values() if v.get("hijri")),"with hijri")
