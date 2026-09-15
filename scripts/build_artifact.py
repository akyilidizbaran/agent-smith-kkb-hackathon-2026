"""Build the artifact HTML from docs/ARCHITECTURE_V3.md + docs/ARCHITECTURE_RESEARCH.md.

Every ```mermaid fence is lifted out as a static <pre class="mermaid"> block (native rendering);
the markdown chunks around them are rendered client-side with marked.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(r"C:\Users\bsroz\AgentSmithler_WorkSpace\docs")
DOCS = [("v3", ROOT / "ARCHITECTURE_V3.md"), ("research", ROOT / "ARCHITECTURE_RESEARCH.md")]
OUT = Path(__file__).with_name("kkb-architecture-v2.html")  # aynı yol = aynı artifact URL; scratchpad kaybolursa yeni artifact açılır  # same path → same artifact URL

FENCE = re.compile(r"```mermaid\n(.*?)```", re.S)


def esc_script(s: str) -> str:
    return s.replace("</script", "<\\/script")


def esc_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


sections_html: list[str] = []
scripts: list[str] = []
for key, path in DOCS:
    md = path.read_text(encoding="utf-8")
    md = re.sub(r"^# .*?\n", "", md, count=1)  # page header carries the H1s
    pos = 0
    idx = 0
    for m in FENCE.finditer(md):
        chunk = md[pos:m.start()]
        sid = f"md-{key}-{idx}"
        scripts.append(f'<script type="text/plain" id="{sid}">{esc_script(chunk)}</script>')
        sections_html.append(f'<div class="md" data-src="{sid}"></div>')
        sections_html.append(f'<div class="diagram"><pre class="mermaid">{esc_html(m.group(1))}</pre></div>')
        pos = m.end()
        idx += 1
    sid = f"md-{key}-{idx}"
    scripts.append(f'<script type="text/plain" id="{sid}">{esc_script(md[pos:])}</script>')
    sections_html.append(f'<div class="md" data-src="{sid}"></div>')
    if key == "v3":
        sections_html.append('<hr class="docsep"><h1 class="doc2" id="arastirma-tabani">Araştırma tabanı ve ADR arşivi (V2)</h1>'
                             '<p class="notice">Aşağıdaki bölüm V3\'ün dayandığı araştırma ve karar kayıtlarıdır; V3 §7\'de listelenen kararlar bu bölümdekileri geçersiz kılar.</p>')

body = "\n".join(sections_html)
scripts_html = "\n".join(scripts)

html = f"""<title>KKB Agentic Analytics — Mimari V3</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{
  --paper:#F3F5F7; --ink:#1B2430; --ink-2:#4A5563; --rule:#D5DBE1; --panel:#FFFFFF;
  --accent:#0F6E7A; --accent-ink:#0B4F58; --accent-soft:#DDEFF1;
  --ok:#2F7D4F; --ok-soft:#E3F1E7; --warn:#B7791F; --warn-soft:#F6ECD6; --bad:#A63D40; --bad-soft:#F3DEDF;
  --code-bg:#E9EDF1; --shadow:0 1px 0 rgba(27,36,48,.06);
}}
@media (prefers-color-scheme: dark){{
  :root:not([data-theme="light"]){{
    --paper:#0F1418; --ink:#E6EAEE; --ink-2:#A6B0BA; --rule:#2A333C; --panel:#151B21;
    --accent:#4FB3BF; --accent-ink:#8ED3DB; --accent-soft:#12303A;
    --ok:#6CC08B; --ok-soft:#173222; --warn:#E0B15A; --warn-soft:#3A2D12; --bad:#E58B8D; --bad-soft:#3B1D1E;
    --code-bg:#1C242C; --shadow:none;
  }}
}}
:root[data-theme="dark"]{{
  --paper:#0F1418; --ink:#E6EAEE; --ink-2:#A6B0BA; --rule:#2A333C; --panel:#151B21;
  --accent:#4FB3BF; --accent-ink:#8ED3DB; --accent-soft:#12303A;
  --ok:#6CC08B; --ok-soft:#173222; --warn:#E0B15A; --warn-soft:#3A2D12; --bad:#E58B8D; --bad-soft:#3B1D1E;
  --code-bg:#1C242C; --shadow:none;
}}
html{{background:var(--paper)}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:"IBM Plex Sans",system-ui,Segoe UI,Roboto,sans-serif;font-size:15.5px;line-height:1.6;padding-inline:clamp(16px,4vw,48px);padding-block:0 96px}}
.wrap{{max-width:1240px;margin:0 auto;display:grid;grid-template-columns:270px minmax(0,1fr);gap:48px}}
@media (max-width:900px){{.wrap{{grid-template-columns:minmax(0,1fr)}} nav.toc{{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--rule);padding-bottom:16px}}}}
header.top{{grid-column:1/-1;padding-block:40px 24px;border-bottom:1px solid var(--rule);margin-bottom:8px}}
.eyebrow{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent-ink)}}
h1.title{{font-family:Archivo,"IBM Plex Sans",sans-serif;font-weight:700;font-size:clamp(28px,4vw,44px);line-height:1.05;letter-spacing:-.01em;margin:8px 0 12px;text-wrap:balance}}
h1.doc2{{font-family:Archivo,"IBM Plex Sans",sans-serif;font-weight:700;font-size:30px;margin:24px 0 8px;text-wrap:balance}}
.meta{{display:flex;flex-wrap:wrap;gap:8px 20px;color:var(--ink-2);font-size:14px;font-variant-numeric:tabular-nums}}
.meta b{{color:var(--ink);font-weight:600}}
nav.toc{{position:sticky;top:0;align-self:start;max-height:100vh;overflow:auto;padding-top:24px;padding-right:12px;border-right:1px solid var(--rule);font-size:13px}}
nav.toc .eyebrow{{margin-bottom:8px;display:block}}
nav.toc a{{display:block;color:var(--ink-2);text-decoration:none;padding:3px 0;border-left:2px solid transparent;padding-left:10px;margin-left:-12px}}
nav.toc a:hover,nav.toc a:focus-visible{{color:var(--accent-ink);border-left-color:var(--accent);outline:none}}
nav.toc a.l3{{padding-left:22px;font-size:12.5px}}
nav.toc a.doc{{font-family:Archivo,sans-serif;font-weight:600;color:var(--ink);margin-top:10px}}
main{{min-width:0;padding-top:24px}}
main h2{{font-family:Archivo,"IBM Plex Sans",sans-serif;font-weight:600;font-size:26px;letter-spacing:-.01em;margin:56px 0 12px;padding-top:12px;border-top:2px solid var(--accent);text-wrap:balance}}
main h3{{font-family:Archivo,"IBM Plex Sans",sans-serif;font-weight:600;font-size:18px;margin:32px 0 8px;text-wrap:balance}}
main p,main li{{max-width:72ch}}
main blockquote{{margin:0 0 20px;padding:12px 18px;border-left:3px solid var(--accent);background:var(--accent-soft);color:var(--ink)}}
main blockquote p{{margin:4px 0;max-width:none}}
main table{{border-collapse:collapse;width:100%;font-size:13.5px;margin:12px 0 20px}}
.tbl{{overflow-x:auto;border:1px solid var(--rule);background:var(--panel);box-shadow:var(--shadow)}}
main th,main td{{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--rule)}}
main th{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-2);background:var(--code-bg)}}
main tr:last-child td{{border-bottom:0}}
main td{{font-variant-numeric:tabular-nums}}
main code{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.9em;background:var(--code-bg);padding:1px 5px;border-radius:3px}}
main pre{{background:var(--code-bg);padding:14px 16px;overflow-x:auto;font-size:12.5px;line-height:1.5;border:1px solid var(--rule)}}
main pre code{{background:none;padding:0;font-size:inherit}}
main hr{{border:0;border-top:1px solid var(--rule);margin:32px 0}}
main hr.docsep{{border-top:3px double var(--accent);margin:72px 0 24px}}
main a{{color:var(--accent-ink)}}
.tag{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.04em;padding:1px 6px;border-radius:3px;white-space:nowrap;font-weight:500}}
.tag-ORG{{background:var(--ok-soft);color:var(--ok)}} .tag-DOC{{background:var(--accent-soft);color:var(--accent-ink)}}
.tag-EMP{{background:var(--ok-soft);color:var(--ok)}} .tag-SRC{{background:var(--accent-soft);color:var(--accent-ink)}}
.tag-INF{{background:var(--warn-soft);color:var(--warn)}} .tag-ASM{{background:var(--bad-soft);color:var(--bad)}}
.tag-REC{{background:var(--code-bg);color:var(--ink-2)}} .tag-ORGq{{background:var(--warn-soft);color:var(--warn)}} .tag-repo{{background:var(--code-bg);color:var(--ink-2)}}
.diagram{{background:var(--panel);border:1px solid var(--rule);padding:16px;overflow-x:auto;margin:16px 0 24px}}
.diagram pre.mermaid{{background:none;border:0;padding:0;margin:0}}
.notice{{font-size:13px;color:var(--ink-2);border:1px dashed var(--rule);padding:10px 14px;margin:0 0 24px;max-width:none}}
:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
@media (prefers-reduced-motion: no-preference){{html{{scroll-behavior:smooth}}}}
</style>

<div class="wrap">
  <header class="top">
    <span class="eyebrow">KKB Hackathon 2026 · Agentic Data Analytics · AgentSmithler</span>
    <h1 class="title">Architecture V3 — Batched ReAct + Boundary Validation</h1>
    <div class="meta">
      <span><b>Tarih</b> 10 Eylül 2026</span>
      <span><b>Dondurma</b> 20 Eylül 2026 · 10 gün</span>
      <span><b>Final</b> 17 Ekim 2026</span>
      <span><b>Tipik soru</b> 2–3 LLM turu · replay'de 0</span>
    </div>
  </header>
  <nav class="toc" aria-label="İçindekiler"><span class="eyebrow">İçindekiler</span><div id="toc"></div></nav>
  <main>
    <p class="notice">Kanıt etiketleri: <span class="tag tag-ORG">ORG</span> organizatör · <span class="tag tag-DOC">DOC</span> resmî doküman · <span class="tag tag-EMP">EMP</span> ekibin MIA ölçümü · <span class="tag tag-SRC">SRC</span> yayın · <span class="tag tag-INF">INF</span> çıkarım · <span class="tag tag-ASM">ASM</span> varsayım · <span class="tag tag-REC">REC</span> öneri.</p>
    {body}
  </main>
</div>

{scripts_html}
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script>
(function(){{
  marked.setOptions({{gfm:true, breaks:false}});
  document.querySelectorAll('div.md').forEach(function(el){{
    var md = document.getElementById(el.dataset.src).textContent;
    el.innerHTML = marked.parse(md);
    el.querySelectorAll('code').forEach(function(c){{
      var m = /^\\[(ORG\\??|DOC|EMP|SRC|INF|ASM|REC|repo)\\]$/.exec(c.textContent.trim());
      if(m){{ var k=m[1].replace('?','q'); var s=document.createElement('span'); s.className='tag tag-'+k; s.textContent=m[1]; c.replaceWith(s); }}
    }});
    el.querySelectorAll('table').forEach(function(t){{ var w=document.createElement('div'); w.className='tbl'; t.parentNode.insertBefore(w,t); w.appendChild(t); }});
  }});
  var toc = document.getElementById('toc'), seen = {{}};
  document.querySelectorAll('main h1.doc2, main h2, main h3').forEach(function(h){{
    if(!h.id){{ var base = h.textContent.toLowerCase().replace(/[^a-z0-9ğüşöçı]+/g,'-').replace(/^-|-$/g,''); var id = base, n = 2; while(seen[id] || document.getElementById(id)){{ id = base + '-' + (n++); }} h.id = id; }}
    seen[h.id] = true;
    var a=document.createElement('a'); a.href='#'+h.id; a.textContent=h.textContent.replace(/^PART\\s+/,'P');
    a.className = h.tagName==='H3' ? 'l3' : (h.tagName==='H1' ? 'doc' : '');
    toc.appendChild(a);
  }});
}})();
</script>
"""
OUT.write_text(html, encoding="utf-8")
print(OUT, len(html))
