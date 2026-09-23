"""kkb_agent_v3 — Batched ReAct + Boundary Validation motoru (docs/calisma-notlari/ARCHITECTURE_V3.md).

`kkb_agent` (ekip motoru) ile AYNI veri katmanını paylaşır ve ona dokunmaz:
contracts/, adapters/, domain.DomainProfile ve golden set oradan import edilir.
Bu paket yalnızca motor katmanıdır: döngü, araç sözleşmesi, sınır doğrulayıcı,
grounding guard, domain markdown'ı. İki motor aynı LakehouseClient üstünde
`scripts/run_benchmark.py` ile karşılaştırılır.
"""
