# ADR-0029: Sınır doğrulayıcı tek modülde; Planner/Retriever/Validator/Narrator rol olarak

**Durum:** Kabul edildi · **Tarih:** 2026-09-12 · **Kaynak:** Büşra'nın V3 `BoundaryValidator`'ı (§3.3), mentör 12 Eylül

## Bağlam
Doğrulama davranışımız güçlüydü ama beş dosyaya dağılmıştı: şema kontrolü `core/tool.py`
ve `core/registry.py`'da, SQL guard adaptörün istisnasını metinden tanıyan bir
heuristikle `tools/lakehouse.py`'da, dönem/kapsam/referans kontrolleri araç gövdelerinin
içinde, döngü/çıkmaz/anlatı kontrolleri `core/agent.py`'da. "Validator nerede?" sorusunun
cevabı bir dosya değil, bir listeydi.

İki dış sebep daha vardı. Büşra V3'te aynı işi tek boru hattı olarak yazmıştı
(şema → SQL guard → referans → politika) ve motor karşılaştırması sonrası uzlaşı
"modüller ortak katmana, tek harness" oldu. Mentör de rolleri "mantıksal sorumluluk
olarak gösterin; ayrı LLM agent olması gerekmez" dedi — göstermek için önce kodda
adlandırılmaları gerekiyordu.

## Karar
**`core/validator.py` — `BoundaryValidator`.** Her araç çağrısı aynı sırayla geçer:

1. **şema** — Pydantic; geçmeyen argümanın referansı da politikası da yok.
2. **SQL guard** — `sql` alanı taşıyan her araç için, araçtan bağımsız; adaptör aynı
   guard'ı yine çalıştırır (ADR-0020, savunma derinliği). Referanstan ÖNCE: yasak bir
   ifadenin referansını doğrulamak anlamsız, "tabloyu düzelt" deyip DROP'u yeniden
   denetmek bir tur yakar.
3. **referans** — aracın `validate_refs` hook'u: seri/kolon/tablo var mı.
4. **politika** — aracın `check_policy` hook'u: referansı sağlam çağrı yine de
   çalışmamalı mı (dönem filtresi yok, sorulan ay kapsam dışı, ifade güvensiz).
5. **run** — doğrulanmış parametrelerle.

Araç yalnız iki hook yazar; sırayı ve hataya sarmayı bilmez. Mesaj metinleri olduğu gibi
taşındı — ölçülerek yazıldılar (ADR-0010/0016/0017/0019). `SQL_FAILED`'i `UNSAFE_SQL`'den
ayıran metin heuristiği kalktı: guard artık ikinci katmanda yapısal olarak yakalıyor.

Bir yan düzeltme: `DATASET_NOT_FOUND` adayları artık **en yakın 8**, tüm katalog değil.
Eski hâli 1620 seride hata mesajını hataya çeviriyordu (ADR-0026 dersi).

**Roller.** `Tool.role` (`retrieve` | `execute`) ve `AgentStep.role`
(`retrieve` | `execute` | `validate` | `narrate`). Doğrulayıcıda takılan çağrı
`validate`; geri gönderme ve grounding düşünceleri `validate`; nihai cevap `narrate`.
İz artık rollerle okunuyor:

```
✓ [retrieve] [1] lakehouse_search(...)
✗ MISSING_PERIOD_FILTER [validate] [2] lakehouse_query(...)
✓ [execute] [3] lakehouse_query(...)
  [narrate] [4] düşünce: nihai cevap
```

**Planner** ayrı bir şey değil: LLM'in kendisi, ve hangi aracı seçtiği bu adımların
sırasında okunur. Bunu saklamıyoruz — 5–6 adımlık sorularda ayrı bir planlama turu
ölçülebilir hiçbir şey kazandırmıyor, bir tur kaybettiriyor.

## Ölçüm
Birim: 130 test; sıra testleri "iki katmanda birden takılabilecek çağrı hangi hatayı
alır" sorusuyla yazıldı (DROP + olmayan tablo → `UNSAFE_SQL`; olmayan tablo + dönem
eksik → `DATASET_NOT_FOUND`; dönem eksik → sorgu hiç çalışmaz). Golden, Silver şeması, taşıma sonrası: **7/7**, 1 araç
hatası (`MISSING_PERIOD_FILTER×1`), anlatı doğrulama 7/7 temiz, roller
`retrieve×24, execute×9, validate×3, narrate×9`. Davranış değişmedi; adres değişti.

## İlgili
ADR-0025 (hata zarfı), ADR-0026 (aday listesi boyutu), ADR-0027 (anlatı doğrulama),
ADR-0028 (erişim katmanı da aynı zarfla döner). V3: `kkb_agent_v3/core/validator.py`.
