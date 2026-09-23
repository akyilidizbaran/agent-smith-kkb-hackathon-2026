"""ADR-0104: tur niyeti tek yerde. Benchmark'ın 76 vakasındaki bütün turların sınıflandırması kilitlidir.

Bir desen değişince bu test hangi turların niyetinin kaydığını listeler; kayma bilinçliyse fikstür
yeniden üretilir ve farkı PR'da gözden geçirilir (DeepSeek 76 vaka: 9 tur yanlış niyetle kaynak özetine gitmişti).
"""

from __future__ import annotations

import json
from pathlib import Path

from kkb_agent.core.turn_intent import classify

FIXTURE = Path(__file__).parent / "fixtures" / "turn_intent_benchmark.json"


def test_benchmark_turn_intents_are_locked() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    drift = []
    for case in cases:
        intent = classify(case["question"])
        flags = sorted(k for k, v in intent.flags().items() if v)
        if intent.kind != case["kind"] or flags != case["flags"]:
            drift.append(f"{case['id']}: {case['kind']} {case['flags']} → {intent.kind} {flags}")
    assert not drift, "niyet kayması:\n" + "\n".join(drift)


def test_no_benchmark_turn_is_a_read_only_source_question() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert not [c["id"] for c in cases if classify(c["question"]).read_only_source]


def test_difference_is_a_transformation_but_farkli_is_not() -> None:
    assert classify("Takip: Aylık farkı hesapla.").transformation
    assert classify("Her ay için önceki aya göre mutlak fark göster").transformation
    assert not classify("Farklı bir kaynaktan getir").transformation


def test_read_only_source_needs_no_table_or_transformation_request() -> None:
    assert classify("Bu verinin kaynağı nedir?").kind == "kaynak"
    assert classify("Bu verinin kaynağını ve aylık değişimini göster").kind != "kaynak"


def test_bare_column_or_ratio_words_are_not_transformations() -> None:
    """Son 3× (23 Eyl): 'kolon/oran' tek başına dönüşüm sayılınca dışa aktarma turunda (F08.2) model istenmemiş aylık
    değişim hesapladı. Eylemle birlikte geçen biçimler ve çekimli 'fark' hâlâ dönüşümdür."""
    for question in ("Ekran tablosuyla kolonlar ve değerler aynı olsun; CSV olarak dışa aktar.",
                     "Takipteki alacak oranı serisini getir.", "Sonuç kolonunun adına x ekle ve tabloyu üret."):
        assert not classify(question).transformation, question
    for question in ("Yeni bir kolon ekle: reel değer.", "Kredi/mevduat oranını hesapla.",
                     "Ay-ay mutlak farklara IQR uygula.", "Aylık farkı hesapla."):
        assert classify(question).transformation, question
    assert not classify("Farklı bir kaynaktan getir.").transformation
