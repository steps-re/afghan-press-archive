"""Vendor-agnostic model bank for HTR.

One interface over every reader we can run on FREE credits:
  - Gemini 2.5 / 3.x on Vertex  (set HTR_PROJECT)
  - GPT-5.x on Azure OpenAI     (optional; set HTR_AZURE_ENDPOINT)

Why a bank: the best reader is SCRIPT-DEPENDENT (measured — Gemini >> GPT on nastaliq;
Latin cursive may flip), and cross-vendor disagreement is a free uncertainty/QA signal.
Add a backend by adding one entry to BACKENDS; everything downstream is model-agnostic.

Secrets: never hardcoded. Gemini uses the ambient gcloud token (VM default SA or
GCLOUD_ACCOUNT). Azure key from $AOAI_KEY or the file at $AOAI_KEY_FILE.
"""
import base64, json, os, subprocess, time, urllib.request, urllib.error

# ---- Gemini (Vertex) ----
GEMINI_PROJECT = os.environ.get("VERTEX_PROJECT", os.environ.get("HTR_PROJECT", ""))
GCLOUD_ACCOUNT = os.environ.get("GCLOUD_ACCOUNT", "")   # empty = ambient identity (VM default SA)
_tok = {"v": None, "e": 0.0}

def _gtoken():
    if _tok["v"] and time.time() < _tok["e"]:
        return _tok["v"]
    cmd = ["gcloud", "auth", "print-access-token"]
    if GCLOUD_ACCOUNT:
        cmd += ["--account", GCLOUD_ACCOUNT]
    _tok["v"] = subprocess.check_output(cmd).decode().strip()
    _tok["e"] = time.time() + 1500
    return _tok["v"]

def _gemini_url(model, location):
    # A tuned model is addressed by its ENDPOINT resource path, not a publisher-model name,
    # and always lives in the region it was tuned in.
    if model.startswith("projects/"):
        loc = model.split("/locations/")[1].split("/")[0]
        host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
        return f"https://{host}/v1/{model}:generateContent", loc
    # Gemini 3.x is served ONLY on the global endpoint; 2.5.x can use any region.
    if model.startswith("gemini-3"):
        location = "global"
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    return (f"https://{host}/v1/projects/{GEMINI_PROJECT}/locations/{location}"
            f"/publishers/google/models/{model}:generateContent"), location

def call_gemini(model, system, user, image_b64=None, max_tokens=16384, temperature=0.1,
                location="us-central1", retries=3):
    parts = []
    if image_b64:
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": image_b64}})
    parts.append({"text": user})
    body = {"contents": [{"role": "user", "parts": parts}],
            "systemInstruction": {"parts": [{"text": system}]},
            # temperature is ignored by 3.x (harmless); kept for 2.5.x
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature}}
    url, _ = _gemini_url(model, location)
    data = json.dumps(body).encode()
    for a in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {_gtoken()}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            c = (d.get("candidates") or [{}])[0]
            fr = c.get("finishReason")
            txt = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts") or []).strip()
            if fr == "MAX_TOKENS":
                txt = (txt + "\n[TRUNCATED—MAX_TOKENS]").strip()
            if not txt and fr in {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}:
                raise RuntimeError(f"blocked: {fr}")
            return txt
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                _tok["v"] = None
            if a < retries and e.code in (401, 403, 429, 500, 502, 503, 504):
                time.sleep(3 * (a + 1)); continue
            raise
        except Exception:
            if a < retries:
                time.sleep(3 * (a + 1)); continue
            raise

# ---- GPT-5.x (Azure OpenAI) ----
AOAI_ENDPOINT = os.environ.get("AOAI_ENDPOINT", os.environ.get("HTR_AZURE_ENDPOINT", ""))
AOAI_API = os.environ.get("AOAI_API_VERSION", "2025-04-01-preview")

def _aoai_key():
    k = os.environ.get("AOAI_KEY", "")
    if k:
        return k
    f = os.environ.get("AOAI_KEY_FILE", "")
    if f and os.path.exists(f):
        return open(f).read().strip()
    raise RuntimeError("set $AOAI_KEY or $AOAI_KEY_FILE for Azure OpenAI")

def call_openai(deployment, system, user, image_b64=None, max_tokens=16384, retries=3):
    content = [{"type": "text", "text": user}]
    if image_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "max_completion_tokens": max_tokens}
    url = f"{AOAI_ENDPOINT}/openai/deployments/{deployment}/chat/completions?api-version={AOAI_API}"
    data = json.dumps(body).encode()
    for a in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "api-key": _aoai_key(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            return (d["choices"][0]["message"]["content"] or "").strip()
        except urllib.error.HTTPError as e:
            if a < retries and e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (a + 1)); continue
            raise
        except Exception:
            if a < retries:
                time.sleep(3 * (a + 1)); continue
            raise

# ---- unified registry ----
# Each backend: (vendor, model_id). transcribe(name, ...) routes to the right vendor.
BACKENDS = {
    "gemini-2.5-pro":        ("gemini", "gemini-2.5-pro"),
    "gemini-3.7-flash":      ("gemini", "gemini-3.7-flash"),
    "gemini-3.1-pro":        ("gemini", "gemini-3.1-pro-preview"),
    "gemini-3.7-flash":      ("gemini", "gemini-3.7-flash"),
    "gpt-5.6-sol":           ("openai", "gpt-5.6-sol"),
    "gpt-5.6-terra":         ("openai", "gpt-5.6-terra"),
    # Our supervised tune of 2.5-pro (htr-afghan-pro-v1, epoch-6 checkpoint). Matches
    # 3.1-pro on effective yield while running on 2.5-pro quota — the throughput arm.
    # Your own supervised-tuned reader, if you have one. Set HTR_TUNED_ENDPOINT to its
    # full endpoint resource path; the entry disappears when unset.
    **({"tuned-pro": ("gemini", os.environ["HTR_TUNED_ENDPOINT"])}
       if os.environ.get("HTR_TUNED_ENDPOINT") else {}),
}
# Backends tuned on our own prompt wording; scoring them on a generic prompt measures
# prompt mismatch, not the model.
TUNED_BACKENDS = {"tuned-2.5-pro"}

def transcribe(backend, system, user, image_b64=None, **kw):
    """Route to a backend by friendly name. Returns text (never raises to the caller for
    a bad backend name -> KeyError is a programming error, let it surface)."""
    vendor, model = BACKENDS[backend]
    if vendor == "gemini":
        return call_gemini(model, system, user, image_b64, **kw)
    if vendor == "openai":
        kw.pop("location", None); kw.pop("temperature", None)   # not accepted by Azure path
        return call_openai(model, system, user, image_b64, **kw)
    raise ValueError(f"unknown vendor {vendor}")
