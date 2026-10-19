import json,subprocess,os,threading
from concurrent.futures import ThreadPoolExecutor
exec(open("dates2.py").read().split("for k in need:")[0])
lock=threading.Lock()
todo=[k for k in need if k not in out and not k.startswith("1-1@")]
def one(k):
    s=its[k]["start"]; txt="\n=== next page ===\n".join(T.get(p,"")[:900] for p in range(s,s+4))
    try:
        r=subprocess.run(["llm","-m","vertex/gemini-3.8-flash","-o","temperature","0",PROMPT+txt],capture_output=True,text=True,env=env,timeout=60,stdin=subprocess.DEVNULL)
        t=r.stdout.strip().strip("`").removeprefix("json").strip(); v=json.loads(t)
    except Exception as e:
        v=None; print("fail",k,type(e).__name__,flush=True)
    if v is not None:
        with lock:
            out[k]=v; json.dump(out,open("dates2.json","w"),ensure_ascii=False,indent=0)
with ThreadPoolExecutor(4) as ex: list(ex.map(one,todo))
print(len(out),"of",len(need),"done",flush=True)
