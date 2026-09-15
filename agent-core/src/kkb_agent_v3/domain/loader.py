"""Domain bilgisi — YAML değil, başlıklı markdown (V3 §3.7).

Text2SqlAgent'ın scenarios.md kalıbı [SRC]: alan bilgisi `## başlık` bölümleri
halinde tutulur; model gerektiğinde `lookup_domain_note` ile ilgili bölümü çeker.
Burada iki tür bölüm var ve ikisi farklı okuyucuya gider:

  MAKİNE bölümleri (sabit başlık, markdown tablosu; kod okur, LLM görmez):
    ## measure_rules      semantic_type → izinli/yasak dönüşüm (boundary validator)
    ## evidence_domains   dış kanıtta öncelikli alan adları (SearchProvider)

  MODEL bölümleri (serbest metin; prompt'a gömülür ya da lookup ile çekilir):
    ## note: <başlık>      tarihli düzenleme/ölçüm notu
    ## template: <başlık>  anlatım şablonu

Bütçe kuralı — ölçülmüş maliyet modelinden [EMP]: bir araç turu ≈ 0,5 s ≈ ~7k
token prefill. Model bölümlerinin toplamı `budget_tokens` altındaysa hepsi
prompt'a GÖMÜLÜR (lookup turu daha pahalı); üstündeyse yalnız başlık dizini
girer ve lookup aracı devreye alınır. Katalog için E8'de kullanılan eşik
mantığının aynısı.

Alias'lar bilerek burada DEĞİL: katalog (`ColumnSpec.aliases`) tek kaynak;
ikinci kopya vintage uyuşmazlığı doğurur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.M)
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")

# Türkçe metinde ~3,5 karakter/token — kaba tahmin [ASM]; eşik zaten yumuşak.
CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


@dataclass(frozen=True)
class MeasureRule:
    semantic_type: str
    allowed: tuple[str, ...]
    forbidden: tuple[str, ...]
    hint: str


@dataclass
class DomainKnowledge:
    source: str = "(yok)"
    measure_rules: dict[str, MeasureRule] = field(default_factory=dict)
    evidence_domains: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)      # başlık → gövde
    templates: dict[str, str] = field(default_factory=dict)  # başlık → gövde

    # ---- model bölümleri ----
    def sections(self) -> dict[str, str]:
        out = {f"note: {k}": v for k, v in self.notes.items()}
        out.update({f"template: {k}": v for k, v in self.templates.items()})
        return out

    def titles(self) -> list[str]:
        return list(self.sections())

    def lookup(self, topic: str) -> tuple[str | None, list[str]]:
        """Başlığa göre bölüm; tam eşleşme yoksa kelime örtüşmesiyle en yakın."""
        secs = self.sections()
        t = _norm(topic)
        for title, body in secs.items():
            if _norm(title) == t or _norm(title.split(":", 1)[-1]) == t:
                return body, [title]
        scored = sorted(
            ((len(set(_norm(k).split()) & set(t.split())), k) for k in secs), reverse=True
        )
        best = [k for s, k in scored if s > 0][:3]
        if best and scored[0][0] >= 1:
            return secs[best[0]], best
        return None, list(secs)[:5]

    def inline_tokens(self) -> int:
        return sum(estimate_tokens(b) for b in self.sections().values())

    def render_for_prompt(self, budget_tokens: int) -> tuple[str, bool]:
        """(metin, lookup_gerekli). Bütçe altındaysa gömülü; üstündeyse yalnız dizin."""
        secs = self.sections()
        if not secs:
            return "", False
        if self.inline_tokens() <= budget_tokens:
            body = "\n\n".join(f"[{title}]\n{text.strip()}" for title, text in secs.items())
            return "ALAN NOTLARI (araç sonuçlarını yorumlarken uy):\n" + body, False
        index = "\n".join(f"  - {t}" for t in secs)
        return (
            "ALAN NOTLARI DİZİNİ — ilgili başlığı lookup_domain_note(topic) ile çek, "
            "hepsini isteme:\n" + index
        ), True


def _norm(s: str) -> str:
    return re.sub(r"[^\wçğıöşü ]+", " ", s.casefold()).strip()


def _parse_table(block: str) -> list[dict[str, str]]:
    rows = [m.group(1) for m in (_TABLE_ROW.match(line) for line in block.splitlines()) if m]
    if len(rows) < 2:
        return []
    header = [h.strip() for h in rows[0].split("|")]
    out: list[dict[str, str]] = []
    for r in rows[1:]:
        cells = [c.strip() for c in r.split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue  # ayraç satırı
        if len(cells) != len(header):
            continue
        out.append(dict(zip(header, cells)))
    return out


def _split_list(s: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in s.split(",") if x.strip() and x.strip() != "-")


def parse_markdown(text: str, source: str = "(metin)") -> DomainKnowledge:
    kn = DomainKnowledge(source=source)
    matches = list(_HEADING.finditer(text))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        body = text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
        key = title.casefold()
        if key == "measure_rules":
            for row in _parse_table(body):
                st = row.get("semantic_type", "").strip()
                if st:
                    kn.measure_rules[st] = MeasureRule(
                        semantic_type=st,
                        allowed=_split_list(row.get("allowed", "")),
                        forbidden=_split_list(row.get("forbidden", "")),
                        hint=row.get("hint", ""),
                    )
        elif key == "evidence_domains":
            kn.evidence_domains = [r["domain"] for r in _parse_table(body) if r.get("domain")]
        elif key.startswith("note:"):
            kn.notes[title.split(":", 1)[1].strip()] = body
        elif key.startswith("template:"):
            kn.templates[title.split(":", 1)[1].strip()] = body
        # Tanınmayan başlıklar (ör. giriş açıklaması) bilerek yok sayılır.
    return kn


def load_domain_file(path: str | Path | None) -> DomainKnowledge:
    """Dosya yoksa boş bilgi — motor alan bilgisi olmadan da çalışır (genericlik)."""
    if path is None:
        return DomainKnowledge()
    p = Path(path)
    if not p.exists():
        return DomainKnowledge(source=f"{p} (yok)")
    return parse_markdown(p.read_text(encoding="utf-8"), source=str(p))


DOMAIN_DIR = Path(__file__).resolve().parent
