#!/usr/bin/env python3
"""Generate the shortlisted design treatments of the Afghan Press Archive.

Every variant renders the SAME real content — the same three pages, the same Persian text, the
same page images from the archive. Nothing is mocked. A design that only looks good on lorem
ipsum is not a design, and Perso-Arabic at 22px behaves nothing like Latin filler.

The range is deliberately wide, from stripped-back brutalism to outright absurdism, with
several routes through Afghan and period-appropriate visual traditions in between.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = json.load(open("/tmp/sample.json", encoding="utf-8"))
ARABIC_FONT = """@font-face{font-family:Amiri;src:url(/fonts/amiri-arabic.woff2) format('woff2');
 unicode-range:U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFC;font-display:swap}"""

AR_TITLE = "آرشیو مطبوعات افغانستان"
EN_TITLE = "Afghan Press Archive"
BLURB = "69,624 pages · 579 volumes · Kabul and elsewhere, 1871–1930s"
CREDIT = "Scans by New York University Libraries · text machine-read, unverified"
# Farsi chrome. The readership for this archive largely reads Persian/Dari, so every study
# has to survive being mirrored -- a design that only works left-to-right is only half a design.
BLURB_FA = "۶۹٬۶۲۴ صفحه · ۵۷۹ جلد · کابل و جاهای دیگر، ۱۸۷۱ تا دههٔ ۱۹۳۰"
CREDIT_FA = "تصاویر از کتابخانه‌های دانشگاه نیویورک · متن ماشین‌خوان و تأییدنشده"
EN_TITLE_FA = "آرشیو مطبوعات افغانستان"

DESIGNS = [
 ("01-brutalist", "Brutalist", "Structure exposed. Monospace, hairline-free, everything a hard edge. No ornament, no comfort, total legibility.", """
 body{background:#fff;color:#000;font:16px/1.45 ui-monospace,'SF Mono',Menlo,monospace;margin:0}
 .wrap{max-width:1000px;margin:0 auto;padding:0 16px}
 header{border:4px solid #000;padding:18px;margin:24px 0}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:40px;line-height:1.3;margin:0}
 .en{font-size:13px;text-transform:uppercase;letter-spacing:.3em;margin:10px 0 0}
 .meta{font-size:12px;text-transform:uppercase;border-top:4px solid #000;margin-top:14px;padding-top:10px}
 .q{width:100%;border:4px solid #000;padding:14px;font:20px/1.4 Amiri,serif;direction:rtl;text-align:right}
 .hit{border:4px solid #000;border-top:0;padding:14px;display:grid;grid-template-columns:90px 1fr;gap:14px}
 .hit:first-of-type{border-top:4px solid #000;margin-top:20px}
 .hit img{width:90px;border:2px solid #000}
 .ref{font-size:11px;text-transform:uppercase;background:#000;color:#fff;padding:2px 6px;display:inline-block}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:21px;line-height:2;margin-top:8px}
 footer{border:4px solid #000;padding:14px;margin:24px 0;font-size:12px;text-transform:uppercase}
 """),
 ("02-swiss", "Swiss / International", "Grid discipline, one accent, nothing decorative. The Müller-Brockmann answer: information as the only ornament.", """
 body{background:#fff;color:#111;font:15px/1.55 Helvetica,'Helvetica Neue',Arial,sans-serif;margin:0}
 .wrap{max-width:1100px;margin:0 auto;padding:0 28px;
   background-image:repeating-linear-gradient(90deg,#f4f4f4 0 1px,transparent 1px 12.5%)}
 header{padding:56px 0 20px;border-bottom:3px solid #111}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:38px;margin:0;font-weight:400}
 .en{font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:#e2241a;margin:8px 0 0;font-weight:700}
 .meta{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#666;margin-top:6px}
 .q{width:66%;border:0;border-bottom:3px solid #111;padding:12px 0;font:22px/1.4 Amiri,serif;
   direction:rtl;text-align:right;margin:34px 0 0;background:transparent}
 .hit{display:grid;grid-template-columns:1fr 3fr;gap:24px;padding:22px 0;border-bottom:1px solid #ddd}
 .hit img{width:100%;max-width:120px}
 .ref{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:#e2241a;font-weight:700}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:21px;line-height:2;margin-top:8px}
 footer{padding:26px 0 60px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#666}
 """),
 ("03-modern-afghan", "Modern Afghan", "Lapis, madder and gold — the pigments of Herat illumination — driving a contemporary layout. Geometry from tilework, not from a CSS framework.", """
 body{background:#fbf7ee;color:#1d1a14;font:17px/1.6 Georgia,serif;margin:0}
 .wrap{max-width:1060px;margin:0 auto;padding:0 26px}
 header{text-align:center;padding:44px 0 0;position:relative}
 .tile{height:64px;background:
   repeating-conic-gradient(from 45deg,#1f3a6e 0 25%,transparent 0 50%) 0 0/34px 34px,
   repeating-conic-gradient(from 45deg,#b08d3f 0 25%,transparent 0 50%) 17px 17px/34px 34px;
   opacity:.28;margin-bottom:26px}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:52px;margin:0;color:#1f3a6e}
 .en{font-size:13px;letter-spacing:.24em;text-transform:uppercase;color:#7c3b2e;margin:10px 0 0}
 .meta{font-size:13px;color:#6f6757;margin-top:8px}
 .q{width:100%;border:2px solid #1f3a6e;border-radius:2px;background:#fff;padding:15px 18px;
   font:25px/1.5 Amiri,serif;direction:rtl;text-align:right;margin:34px 0 0}
 .hit{display:grid;grid-template-columns:96px 1fr;gap:20px;padding:20px 0;border-bottom:1px solid #e3d9c2}
 .hit img{width:96px;border:3px solid #b08d3f}
 .ref{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#b08d3f}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:23px;line-height:2.15;margin-top:8px}
 footer{margin-top:44px;border-top:3px double #1f3a6e;padding:20px 0 60px;font-size:14px;color:#6f6757}
 """),
 ("04-illuminated", "Illuminated manuscript", "Ruled margins, gold leaf, a sarlawh over the title. The page treated as a codex opening rather than a screen.", """
 body{background:#f7f0dd;color:#2a2114;font:17px/1.7 'Iowan Old Style',Palatino,Georgia,serif;margin:0}
 .wrap{max-width:920px;margin:0 auto;padding:0 30px}
 header{text-align:center;padding:40px 0 0}
 .sarlawh{height:56px;background:
   radial-gradient(circle at 50% 100%,#b08d3f 0 6px,transparent 6px),
   repeating-linear-gradient(90deg,#7c3b2e 0 2px,transparent 2px 16px);
   border-bottom:3px double #b08d3f;opacity:.8}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:50px;margin:22px 0 0;color:#5c2018}
 .en{font-size:12.5px;letter-spacing:.26em;text-transform:uppercase;color:#8a7a52;margin:10px 0 0}
 .meta{font-size:13px;color:#8a7a52;margin-top:6px;font-style:italic}
 .frame{border:2px solid #b08d3f;outline:1px solid #b08d3f;outline-offset:5px;padding:26px;margin:34px 0}
 .q{width:100%;border:0;border-bottom:1px solid #b08d3f;background:transparent;padding:10px 0;
   font:24px/1.5 Amiri,serif;direction:rtl;text-align:right}
 .hit{display:grid;grid-template-columns:88px 1fr;gap:20px;padding:18px 0;border-bottom:1px dotted #c9b071}
 .hit img{width:88px;border:1px solid #b08d3f;outline:3px solid #f7f0dd;outline-offset:-6px}
 .ref{font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:#8a7a52}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:23px;line-height:2.2;margin-top:8px}
 footer{margin-top:40px;border-top:3px double #b08d3f;padding:18px 0 60px;font-size:13.5px;color:#8a7a52}
 """),
 ("05-broadsheet", "Broadsheet", "A newspaper about newspapers. Dense columns, hard rules, a nameplate — the register these papers were actually printed in.", """
 body{background:#f4f1e8;color:#111;font:15px/1.5 'Times New Roman',Times,serif;margin:0}
 .wrap{max-width:1120px;margin:0 auto;padding:0 22px}
 header{text-align:center;padding:26px 0 0;border-bottom:1px solid #111}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:56px;margin:0;letter-spacing:-.01em}
 .en{font-size:11px;letter-spacing:.36em;text-transform:uppercase;margin:6px 0 12px}
 .rule2{border-top:5px solid #111;border-bottom:1px solid #111;height:3px;margin-bottom:6px}
 .meta{display:flex;justify-content:space-between;font-size:11px;text-transform:uppercase;
   letter-spacing:.08em;padding:6px 0;border-bottom:1px solid #111}
 .q{width:100%;border:1px solid #111;background:#fff;padding:11px;font:22px/1.4 Amiri,serif;
   direction:rtl;text-align:right;margin:20px 0}
 .cols{column-count:2;column-gap:30px;column-rule:1px solid #999}
 .hit{break-inside:avoid;padding:14px 0;border-bottom:1px solid #bbb}
 .hit img{width:100%;margin-bottom:8px;filter:grayscale(1) contrast(1.1)}
 .ref{font-size:10.5px;text-transform:uppercase;letter-spacing:.1em;border-bottom:1px solid #111}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:20px;line-height:1.95;margin-top:6px}
 footer{border-top:5px solid #111;margin-top:26px;padding:14px 0 60px;font-size:11px;text-transform:uppercase}
 """),
 ("06-absurdist", "Absurdist", "Type as event. Scale collisions, a colour that should not work, the archive shouting instead of whispering. Included because you asked how far it goes.", """
 body{background:#f2e600;color:#12005e;font:18px/1.4 'Arial Black',Impact,sans-serif;margin:0;overflow-x:hidden}
 .wrap{max-width:1100px;margin:0 auto;padding:0 20px}
 header{padding:30px 0 0}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:96px;line-height:.95;margin:0;
   color:#ff2d95;text-shadow:6px 6px 0 #12005e;transform:rotate(-2deg)}
 .en{font-size:26px;text-transform:uppercase;letter-spacing:-.02em;margin:14px 0 0;
   background:#12005e;color:#f2e600;display:inline-block;padding:4px 12px;transform:rotate(1deg)}
 .meta{font-size:15px;margin-top:14px;background:#fff;display:inline-block;padding:5px 10px}
 .q{width:100%;border:8px solid #12005e;background:#fff;padding:18px;
   font:34px/1.3 Amiri,serif;direction:rtl;text-align:right;margin:26px 0;transform:rotate(-.6deg)}
 .hit{display:grid;grid-template-columns:130px 1fr;gap:18px;background:#fff;border:6px solid #12005e;
   padding:16px;margin-bottom:20px}
 .hit:nth-child(even){transform:rotate(.7deg);background:#ff2d95;color:#fff}
 .hit img{width:130px;border:5px solid #12005e}
 .ref{font-size:13px;text-transform:uppercase;background:#12005e;color:#f2e600;padding:3px 8px;display:inline-block}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:26px;line-height:1.85;margin-top:10px}
 footer{background:#12005e;color:#f2e600;padding:18px;margin:20px 0 60px;font-size:14px;text-transform:uppercase}
 """),
 ("07-terminal", "Archive terminal", "The corpus as a machine you query. Amber phosphor, monospace, counts everywhere. Honest about what this actually is underneath.", """
 body{background:#12100c;color:#ffb642;font:14px/1.5 ui-monospace,'SF Mono',Menlo,monospace;margin:0}
 .wrap{max-width:1000px;margin:0 auto;padding:0 18px}
 header{padding:26px 0 10px;border-bottom:1px solid #4a3a18}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:34px;margin:0;color:#ffd79a}
 .en{font-size:12px;letter-spacing:.2em;text-transform:uppercase;margin:8px 0 0;color:#8a6a2a}
 .meta{font-size:12px;color:#8a6a2a;margin-top:6px}
 .q{width:100%;background:#1b1710;border:1px solid #4a3a18;color:#ffb642;padding:11px;
   font:19px/1.4 Amiri,serif;direction:rtl;text-align:right;margin:20px 0}
 .hit{display:grid;grid-template-columns:70px 1fr;gap:14px;padding:12px 0;border-bottom:1px solid #2a2216}
 .hit img{width:70px;filter:sepia(1) hue-rotate(-12deg) brightness(.85)}
 .ref{font-size:11px;color:#8a6a2a}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:20px;line-height:2;margin-top:6px;color:#ffd79a}
 footer{border-top:1px solid #4a3a18;margin-top:22px;padding:14px 0 60px;font-size:11.5px;color:#8a6a2a}
 """),
 ("08-constructivist", "Constructivist", "1920s again — diagonals, primary blocks, type as structural element. The visual language contemporary with the later half of this archive.", """
 body{background:#efece4;color:#111;font:16px/1.5 Helvetica,Arial,sans-serif;margin:0}
 .wrap{max-width:1060px;margin:0 auto;padding:0 24px}
 header{position:relative;padding:44px 0 22px;overflow:hidden}
 header:before{content:"";position:absolute;right:-60px;top:-40px;width:280px;height:280px;
   background:#d81e05;transform:rotate(24deg)}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:50px;margin:0;position:relative}
 .en{font-size:13px;letter-spacing:.2em;text-transform:uppercase;margin:10px 0 0;position:relative;font-weight:700}
 .meta{font-size:12.5px;margin-top:8px;position:relative;color:#444}
 .q{width:100%;border:0;border-bottom:6px solid #111;background:transparent;padding:12px 0;
   font:25px/1.4 Amiri,serif;direction:rtl;text-align:right;margin:28px 0 0}
 .hit{display:grid;grid-template-columns:100px 1fr;gap:20px;padding:20px 0;border-bottom:2px solid #111}
 .hit img{width:100px;border-left:8px solid #d81e05}
 .ref{font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;
   background:#111;color:#efece4;padding:2px 7px;display:inline-block}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:22px;line-height:2.1;margin-top:9px}
 footer{margin-top:34px;border-top:6px solid #d81e05;padding:16px 0 60px;font-size:12.5px}
 """),
 ("09-editorial", "Editorial", "A serious magazine. Big display serif, wide margins, the page image treated as a plate. Reads like a long essay you want to sit with.", """
 body{background:#fffdf8;color:#1a1a1a;font:18px/1.72 'Iowan Old Style',Palatino,Georgia,serif;margin:0}
 .wrap{max-width:860px;margin:0 auto;padding:0 30px}
 header{padding:76px 0 0}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:62px;line-height:1.15;margin:0}
 .en{font-size:12.5px;letter-spacing:.28em;text-transform:uppercase;color:#8a8378;margin:18px 0 0}
 .meta{font-size:16px;color:#8a8378;margin-top:12px;font-style:italic;max-width:44ch}
 .q{width:100%;border:0;border-bottom:1px solid #ccc4b6;background:transparent;padding:14px 0;
   font:27px/1.5 Amiri,serif;direction:rtl;text-align:right;margin:44px 0 0}
 .hit{padding:34px 0;border-bottom:1px solid #eee6d8}
 .hit img{width:100%;max-width:520px;display:block;margin-bottom:16px}
 .ref{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#8a8378}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:25px;line-height:2.2;margin-top:10px}
 footer{margin-top:46px;padding:22px 0 70px;font-size:15px;color:#8a8378;border-top:1px solid #eee6d8}
 """),
 ("10-museum", "Museum", "Almost nothing. Enormous plates, whispered captions, air. The object is the exhibit and the interface gets out of the way.", """
 body{background:#fcfcfa;color:#2b2b2b;font:15px/1.7 'Helvetica Neue',Helvetica,Arial,sans-serif;margin:0}
 .wrap{max-width:1180px;margin:0 auto;padding:0 40px}
 header{padding:96px 0 0;max-width:620px}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:44px;margin:0;font-weight:400}
 .en{font-size:10.5px;letter-spacing:.34em;text-transform:uppercase;color:#9a968e;margin:20px 0 0}
 .meta{font-size:13px;color:#9a968e;margin-top:10px}
 .q{width:100%;border:0;border-bottom:1px solid #e6e3dc;background:transparent;padding:16px 0;
   font:23px/1.5 Amiri,serif;direction:rtl;text-align:right;margin:56px 0 0}
 .hit{display:grid;grid-template-columns:1fr 1fr;gap:44px;padding:64px 0;align-items:center}
 .hit img{width:100%;box-shadow:0 1px 0 #e6e3dc}
 .ref{font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:#9a968e}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:22px;line-height:2.25;margin-top:14px;color:#4a4a4a}
 footer{margin-top:40px;padding:26px 0 90px;font-size:11.5px;letter-spacing:.1em;
   text-transform:uppercase;color:#9a968e;border-top:1px solid #e6e3dc}
 """),
 ("11-synthesis-cool", "Synthesis \u2014 cool", "The four you chose, resolved. Swiss modular grid and constructivist blocks carrying the lapis-gold-madder palette of Herat illumination. Structure does the work; ornament is one band of tilework.", """
 body{background:#f7f5ef;color:#16161a;font:16px/1.6 'Helvetica Neue',Helvetica,Arial,sans-serif;margin:0}
 .wrap{max-width:1080px;margin:0 auto;padding:0 30px}
 .band{height:8px;background:linear-gradient(90deg,#1f3a6e 0 62%,#b08d3f 62% 84%,#7c3b2e 84% 100%)}
 .plate{background:#1f3a6e;color:#fff;padding:38px 30px 30px;margin:0 -30px;position:relative;overflow:hidden}
 .plate:after{content:"";position:absolute;right:-70px;bottom:-70px;width:230px;height:230px;
   background:#b08d3f;opacity:.22;transform:rotate(28deg)}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:54px;line-height:1.25;margin:0;position:relative}
 .en{font-size:11.5px;letter-spacing:.28em;text-transform:uppercase;margin:14px 0 0;
   color:#c9d4e8;position:relative;font-weight:700}
 .meta{font-size:13px;color:#a8b6d0;margin-top:8px;position:relative}
 .tilerule{height:20px;margin:0 -30px;background:
   repeating-conic-gradient(from 45deg,#1f3a6e 0 25%,transparent 0 50%) 0 0/20px 20px;opacity:.2}
 .q{width:100%;border:0;border-bottom:4px solid #16161a;background:transparent;padding:16px 0;
   font:27px/1.45 Amiri,serif;direction:rtl;text-align:right;margin:34px 0 0;outline:none}
 .hit{display:grid;grid-template-columns:104px 1fr;gap:26px;padding:24px 0;border-bottom:1px solid #ddd8cb}
 .hit img{width:104px;border-left:6px solid #b08d3f}
 .ref{font-size:11px;letter-spacing:.16em;text-transform:uppercase;font-weight:700;
   background:#16161a;color:#f7f5ef;padding:2px 8px;display:inline-block}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:24px;line-height:2.15;margin-top:11px}
 footer{margin-top:38px;border-top:8px solid #1f3a6e;padding:18px 0 60px;font-size:12.5px;color:#5d5a52}
 html[dir=rtl] .plate:after{right:auto;left:-70px}
 html[dir=rtl] .hit img{border-left:0;border-right:6px solid #b08d3f}
 """),
 ("12-synthesis-warm", "Synthesis \u2014 warm", "The same spine turned toward the manuscript: paper ground, ruled gold frame, a khatam headpiece \u2014 still on a strict grid, with constructivist weight in the rules.", """
 body{background:#faf5e8;color:#221d14;font:16.5px/1.65 'Helvetica Neue',Helvetica,Arial,sans-serif;margin:0}
 .wrap{max-width:1000px;margin:0 auto;padding:0 32px}
 header{text-align:center;padding:34px 0 0}
 .khatam{height:26px;background:
   repeating-conic-gradient(from 45deg,#7c3b2e 0 25%,transparent 0 50%) 0 0/26px 26px,
   repeating-conic-gradient(from 45deg,#b08d3f 0 25%,transparent 0 50%) 13px 13px/26px 26px;
   opacity:.5}
 .ar{font-family:Amiri,serif;direction:rtl;font-size:56px;margin:26px 0 0;color:#1f3a6e;line-height:1.2}
 .en{font-size:11.5px;letter-spacing:.3em;text-transform:uppercase;color:#7c3b2e;margin:14px 0 0;font-weight:700}
 .meta{font-size:13px;color:#786a4e;margin-top:8px}
 .frame{border:3px solid #1f3a6e;outline:1px solid #b08d3f;outline-offset:6px;padding:30px;margin:36px 0 0}
 .q{width:100%;border:0;border-bottom:3px solid #b08d3f;background:transparent;padding:14px 0;
   font:27px/1.45 Amiri,serif;direction:rtl;text-align:right;outline:none}
 .hit{display:grid;grid-template-columns:96px 1fr;gap:24px;padding:22px 0;border-bottom:1px solid #e3d8bd}
 .hit img{width:96px;border:2px solid #b08d3f}
 .ref{font-size:11px;letter-spacing:.16em;text-transform:uppercase;font-weight:700;color:#1f3a6e}
 .txt{font-family:Amiri,serif;direction:rtl;text-align:right;font-size:24px;line-height:2.2;margin-top:10px}
 footer{margin-top:34px;border-top:6px solid #7c3b2e;padding:18px 0 60px;font-size:12.5px;color:#786a4e}
 """),
]

# Shortlist: the four that survived review, plus the synthesis they pointed at. The rest stay
# in the list above so the exploration is not lost, but they are not built or published.
KEEP = {"02-swiss", "03-modern-afghan", "04-illuminated", "08-constructivist", "12-synthesis-warm"}
DESIGNS = [d for d in DESIGNS if d[0] in KEEP]

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{n}. {name} — Afghan Press Archive design study</title>
<style>{font}
*{{box-sizing:border-box}}
{css}
.bar{{position:fixed;top:0;left:0;right:0;background:#111;color:#fff;font:12px/1 -apple-system,system-ui,sans-serif;
 padding:9px 14px;z-index:99;display:flex;gap:14px;align-items:center;letter-spacing:.06em}}
.bar a{{color:#fff;text-decoration:none;border-bottom:1px solid #666}}
.bar b{{font-weight:600}} .bar span{{opacity:.65}}
.bar button{{background:transparent;border:1px solid #666;color:#fff;font:inherit;font-size:11px;
 padding:3px 9px;cursor:pointer;border-radius:2px}}
.tools{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
.tools .q{{flex:1;min-width:240px}}
#mode,.dl{{font:inherit;font-size:12px;padding:6px 10px;background:transparent;color:inherit;
 border:1px solid currentColor;cursor:pointer;text-decoration:none;letter-spacing:.06em}}
.count{{font-size:12px;letter-spacing:.12em;text-transform:uppercase;opacity:.65;padding:10px 0}}
.hint{{font-size:13px;opacity:.7}}
.hit{{cursor:pointer}}
body{{padding-top:34px}}
html[dir=rtl] .hit{{direction:rtl}}
html[dir=rtl] .cols{{direction:rtl}}
</style></head><body>
<div class="bar"><b>{n} / {total} · {name}</b><span>{tag}</span>
 <span style="flex:1"></span><button id="lang">فارسی</button><a href="/">all</a>{prev}{next}</div>
<div class="wrap">
<header>{orn}
  <div class="{platecls}">
  <h1 class="ar">{ar}</h1>
  <p class="en" data-en="{en}" data-fa="{en_fa}">{en}</p>
  <p class="meta" data-en="{blurb}" data-fa="{blurb_fa}">{blurb}</p>
  </div>{tilerule}
</header>
{frame_open}
<div class="tools">
  <input class="q" value="ترقیات مدنیه" placeholder="جستجو…">
  <select id="mode">
    <option value="trigram">words &amp; phrases</option>
    <option value="semantic">subject</option>
    <option value="hybrid">both</option>
  </select>
  <a class="dl" href="https://afghanpress.org/api/download/corpus.jsonl">download corpus</a>
</div>
<div class="{colcls}">
{hits}
</div>
{frame_close}
<footer data-en="{credit}" data-fa="{credit_fa}">{credit}</footer>
</div>
<script src="/app.js"></script>
<script>
var L=localStorage.getItem('adl_lang')||'en';
function apply(){{
  var fa=L==='fa';
  document.documentElement.dir=fa?'rtl':'ltr';
  document.documentElement.lang=fa?'fa':'en';
  document.querySelectorAll('[data-en]').forEach(function(el){{
    el.textContent = fa ? el.dataset.fa : el.dataset.en;
  }});
  document.getElementById('lang').textContent = fa ? 'English' : 'فارسی';
}}
document.getElementById('lang').onclick=function(){{
  L = L==='fa' ? 'en' : 'fa'; localStorage.setItem('adl_lang',L); apply();
}};
apply();
</script>
</body></html>"""

def hit_html(r, cls):
    return (f'<div class="hit"><img loading="lazy" src="{r["img"]}" alt="">'
            f'<div><span class="ref">{r["book"]} · page {r["page"]}</span>'
            f'<div class="txt">{r["text"]}</div></div></div>')

os.makedirs(HERE, exist_ok=True)
cards = []
for i, (slug, name, tag, css) in enumerate(DESIGNS, 1):
    if slug.startswith("11"):
        orn = '<div class="band"></div>'
    elif slug.startswith("12"):
        orn = '<div class="khatam"></div>'
    else:
        orn = '<div class="tile"></div>' if slug.startswith("03") else (
          '<div class="sarlawh"></div>' if slug.startswith("04") else (
          '<div class="rule2"></div>' if slug.startswith("05") else ""))
    if slug.startswith("05"):
        orn = ""
    frame_open = '<div class="frame">' if slug.startswith(("04", "12")) else ""
    frame_close = "</div>" if slug.startswith(("04", "12")) else ""
    colcls = "cols" if slug.startswith("05") else "hits"
    hits = "\n".join(hit_html(r, colcls) for r in SAMPLE)
    prev = f' <a href="/{DESIGNS[i-2][0]}.html">← prev</a>' if i > 1 else ""
    nxt = f' <a href="/{DESIGNS[i][0]}.html">next →</a>' if i < len(DESIGNS) else ""
    # broadsheet wants its nameplate rules between title and meta
    head_extra = '<div class="rule2"></div>' if slug.startswith("05") else ""
    html = PAGE.format(n=i, total=len(DESIGNS), name=name, tag=tag, font=ARABIC_FONT, css=css, orn=orn + head_extra,
                       ar=AR_TITLE, en=EN_TITLE, en_fa=EN_TITLE_FA, blurb=BLURB,
                       blurb_fa=BLURB_FA, credit=CREDIT, credit_fa=CREDIT_FA, hits=hits,
                       platecls=("plate" if slug.startswith("11") else "head"),
                       tilerule=('<div class="tilerule"></div>' if slug.startswith("11") else ""),
                       colcls=colcls, frame_open=frame_open, frame_close=frame_close,
                       prev=prev, next=nxt)
    open(os.path.join(HERE, f"{slug}.html"), "w", encoding="utf-8").write(html)
    cards.append((i, slug, name, tag))

INDEX = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Afghan Press Archive — design studies</title>
<style>%s
*{box-sizing:border-box}
body{background:#faf6ec;color:#23201a;font:17px/1.6 'Iowan Old Style',Palatino,Georgia,serif;margin:0}
.wrap{max-width:940px;margin:0 auto;padding:0 28px}
header{padding:56px 0 0;text-align:center}
h1{font-family:Amiri,serif;direction:rtl;font-size:44px;margin:0}
.en{font-size:13px;letter-spacing:.24em;text-transform:uppercase;color:#6f6757;margin:10px 0 0}
.lede{max-width:60ch;margin:24px auto 0;color:#6f6757;font-size:16px}
.rules{border-top:2px solid #23201a;border-bottom:1px solid #23201a;height:4px;margin:26px 0 34px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:22px;padding-bottom:70px}
.card{border:1px solid #ddd4be;padding:18px;text-decoration:none;color:inherit;display:block;background:#fffdf7}
.card:hover{border-color:#7c3b2e}
.num{font-size:11.5px;letter-spacing:.16em;text-transform:uppercase;color:#7c3b2e}
.name{font-size:21px;margin:7px 0 8px}
.tag{font-size:14px;color:#6f6757;line-height:1.5}
</style></head><body><div class="wrap">
<header><h1>آرشیو مطبوعات افغانستان</h1><p class="en">Design studies</p>
<p class="lede">The same archive rendered several ways. Each one is a working interface over the
live collection rather than a mock-up: search it, open a page, page through the scan, switch the
interface to Persian. Nothing here is filler text.</p>
<div class="rules"></div></header>
<div class="grid">%s</div>
</div>
<script src="/app.js"></script>
<script>
var L=localStorage.getItem('adl_lang')||'en';
function apply(){
  var fa=L==='fa';
  document.documentElement.dir=fa?'rtl':'ltr';
  document.documentElement.lang=fa?'fa':'en';
  document.querySelectorAll('[data-en]').forEach(function(el){
    el.textContent = fa ? el.dataset.fa : el.dataset.en;
  });
  document.getElementById('lang').textContent = fa ? 'English' : 'فارسی';
}
document.getElementById('lang').onclick=function(){
  L = L==='fa' ? 'en' : 'fa'; localStorage.setItem('adl_lang',L); apply();
};
apply();
</script>
</body></html>""" % (ARABIC_FONT, "\n".join(
    f'<a class="card" href="/{s}.html"><div class="num">{i:02d}</div>'
    f'<div class="name">{n}</div><div class="tag">{t}</div></a>' for i, s, n, t in cards))
open(os.path.join(HERE, "index.html"), "w", encoding="utf-8").write(INDEX)
print(f"wrote {len(cards)} designs + index")
