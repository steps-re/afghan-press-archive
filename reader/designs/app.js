/* Shared behaviour for the design studies.
   Every study drives the REAL archive API, so each one can be judged as a working interface
   rather than a picture: live search over 69,624 pages, a page reader with the actual scan,
   downloads, and shareable links. The markup and class names are identical across studies —
   only each study's CSS differs — so any difference you see is genuinely the design. */
const API = "https://afghanpress.org";
const $ = s => document.querySelector(s);
const esc = s => (s || "").replace(/[<>&]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
const faD = n => String(n).replace(/[0-9]/g, d => "۰۱۲۳۴۵۶۷۸۹"[d]);
const isFA = () => document.documentElement.dir === "rtl";
const T = {
  searching: ["searching…", "در حال جستجو…"], none: ["nothing found", "چیزی یافت نشد"],
  pages: ["pages", "صفحه"], prev: ["← previous", "→ پیشین"], next: ["next →", "پسین ←"],
  close: ["close", "بستن"], dl: ["download volume", "دریافت این جلد"],
  share: ["copy link", "کپی نشانی"], copied: ["link copied", "نشانی کپی شد"],
  src: ["scan at NYU", "تصویر در NYU"], hint: ["Try a sentence — short phrases miss more often.",
        "یک جملهٔ کامل بهتر نتیجه می‌دهد؛ عبارت‌های کوتاه بیشتر خطا می‌کنند."],
};
const t = k => T[k][isFA() ? 1 : 0];

/* ---- reader ------------------------------------------------------------------------ */
function ensureModal() {
  if ($("#rdr")) return;
  const d = document.createElement("dialog");
  d.id = "rdr";
  d.innerHTML = `<div class="rdr-in">
    <div class="rdr-bar">
      <span class="rdr-ref" id="rref"></span>
      <span style="flex:1"></span>
      <button id="rprev"></button><button id="rnext"></button>
      <button id="rshare"></button><button id="rdl"></button><button id="rclose"></button>
    </div>
    <div class="rdr-body">
      <div class="rdr-plate"><img id="rimg" alt=""></div>
      <div class="rdr-text"><div id="rtxt"></div><p class="rdr-meta" id="rmeta"></p></div>
    </div></div>`;
  document.body.appendChild(d);
  const st = document.createElement("style");
  // Deliberately minimal: inherits each study's own colours and type so the reader looks like
  // it belongs to that design instead of overriding it.
  st.textContent = `#rdr{padding:0;border:2px solid currentColor;background:inherit;color:inherit;
    width:min(1200px,95vw);max-height:94vh;font:inherit}
   #rdr::backdrop{background:rgba(0,0,0,.6)}
   .rdr-bar{display:flex;gap:8px;align-items:center;padding:10px 14px;border-bottom:2px solid currentColor;
     font-size:12px;letter-spacing:.08em;text-transform:uppercase}
   .rdr-bar button{font:inherit;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
     background:transparent;border:1px solid currentColor;color:inherit;padding:4px 9px;cursor:pointer}
   .rdr-body{display:grid;grid-template-columns:1fr 1fr;max-height:84vh}
   .rdr-plate{overflow:auto;background:#fff;order:2;border-left:1px solid currentColor}
   .rdr-plate img{width:100%;display:block}
   .rdr-text{overflow:auto;padding:20px 22px}
   #rtxt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:23px;line-height:2.2;white-space:pre-wrap}
   .rdr-meta{font-size:12px;opacity:.7;margin-top:18px;border-top:1px solid currentColor;padding-top:10px}
   html[dir=rtl] .rdr-plate{order:0;border-left:0;border-right:1px solid currentColor}
   @media(max-width:820px){.rdr-body{grid-template-columns:1fr}.rdr-plate{order:0}}`;
  document.head.appendChild(st);
  $("#rclose").onclick = () => $("#rdr").close();
  $("#rprev").onclick = () => cur.page > cur.lo && openPage(cur.book, cur.page - 1);
  $("#rnext").onclick = () => cur.page < cur.hi && openPage(cur.book, cur.page + 1);
  $("#rshare").onclick = async () => {
    const u = `${location.origin}${location.pathname}?p=${cur.book}/${cur.page}`;
    try { await navigator.clipboard.writeText(u); $("#rshare").textContent = t("copied"); }
    catch { prompt("Copy this link:", u); }
    setTimeout(() => $("#rshare").textContent = t("share"), 1600);
  };
  addEventListener("keydown", e => {
    if (!$("#rdr").open) return;
    if (e.key === "ArrowLeft") $("#rnext").click();
    if (e.key === "ArrowRight") $("#rprev").click();
  });
}
let cur = { book: null, page: null, lo: 1, hi: 1 };
async function openPage(book, page) {
  ensureModal();
  const d = await (await fetch(`${API}/api/page/${book}/${page}`)).json();
  cur = { book, page, lo: d.first_page, hi: d.last_page };
  $("#rimg").src = d.image; $("#rtxt").textContent = d.text;
  $("#rref").textContent = `${book} · ${isFA() ? faD(page) : page} / ${isFA() ? faD(d.last_page) : d.last_page}`;
  $("#rprev").textContent = t("prev"); $("#rnext").textContent = t("next");
  $("#rclose").textContent = t("close"); $("#rshare").textContent = t("share");
  $("#rdl").textContent = t("dl");
  $("#rdl").onclick = () => location.href = `${API}/api/download/book/${book}.jsonl`;
  const meta = $("#rmeta"); meta.textContent = "";
  const mk = (href, label) => { const a = document.createElement("a");
    a.href = href; a.target = "_blank"; a.rel = "noopener"; a.textContent = label; return a; };
  meta.append(mk(d.source, t("src")), " · ", mk(d.source_pdf, "PDF"),
              " · machine-read, unverified — the scan is the source of record");
  history.replaceState({}, "", `?p=${book}/${page}`);
  $("#rdr").showModal();
}

/* ---- search ------------------------------------------------------------------------ */
async function runSearch(q) {
  const box = $(".results") || (() => {
    const e = document.createElement("div"); e.className = "results";
    ($(".cols") || $(".hits") || $(".wrap")).appendChild(e); return e;
  })();
  box.innerHTML = `<div class="count">${t("searching")}</div>`;
  const mode = $("#mode") ? $("#mode").value : "trigram";
  const r = await (await fetch(`${API}/api/search?q=${encodeURIComponent(q)}&mode=${mode}&limit=20`)).json();
  if (!r.results.length) {
    box.innerHTML = `<div class="count">${t("none")}</div><p class="hint">${t("hint")}</p>`; return;
  }
  const n = isFA() ? faD(r.results.length) : r.results.length;
  box.innerHTML = `<div class="count">${n} ${t("pages")} · ${isFA() ? faD(r.ms) : r.ms} ms</div>` +
    r.results.map(x => `<div class="hit" data-b="${x.book}" data-p="${x.page}">
      <img loading="lazy" src="${x.image}" alt="">
      <div><span class="ref">${x.book} · ${isFA() ? faD(x.page) : x.page}</span>
      <div class="txt">${esc(x.snippet)}</div></div></div>`).join("");
  box.querySelectorAll(".hit").forEach(el =>
    el.onclick = () => openPage(el.dataset.b, +el.dataset.p));
}

/* ---- wire up ------------------------------------------------------------------------ */
addEventListener("DOMContentLoaded", () => {
  const q = $(".q");
  if (q) {
    q.readOnly = false;
    q.addEventListener("keydown", e => { if (e.key === "Enter") runSearch(q.value.trim()); });
  }
  // the sample hits in the static markup become live: clicking one opens the real page
  document.querySelectorAll(".hit").forEach(el => {
    const ref = el.querySelector(".ref");
    if (!ref) return;
    const m = ref.textContent.match(/(adl\d+)\D+(\d+)/);
    if (m) { el.style.cursor = "pointer"; el.onclick = () => openPage(m[1], +m[2]); }
  });
  const p = new URLSearchParams(location.search).get("p");
  if (p && /^adl\d+\/\d+$/.test(p)) { const [b, n] = p.split("/"); openPage(b, +n); }
});
