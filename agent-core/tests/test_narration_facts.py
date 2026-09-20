from __future__ import annotations

import pandas as pd

from kkb_agent.core.narration_facts import build_narration_facts


def test_facts_are_bounded_and_grounded_in_table_metadata_and_cells() -> None:
    frame = pd.DataFrame({
        "period": pd.to_datetime(["2024-02-29", "2024-01-31", "2024-03-31"]),
        "measure": [12.5, 10.0, None],
        "category": ["A", "B", "A"],
    })

    facts = build_narration_facts(
        frame,
        sources=["Official source", "Official source"],
        column_labels={"measure": "Observed measure"},
        units={"measure": "million units"},
        verified_notes=["Tool verified a period-end balance."],
    )

    assert facts.row_count == 3 and facts.column_count == 3
    assert facts.date_column == "period"
    assert facts.period_start == "2024-01-31" and facts.period_end == "2024-03-31"
    assert facts.source_names == ("Official source",)
    assert "Observed measure (million units)" in facts.text
    assert "2024-01-31: 10" in facts.text
    assert "2024-02-29: 12,5" in facts.text
    assert "1 eksik değer" in facts.text
    assert "Official source" in facts.text
    assert "Tool verified a period-end balance." in facts.text
    assert "ortalama" not in facts.text.casefold()
    assert "2024-03-31:" not in facts.text.split("Observed measure", 1)[1].split("Gözlenen uçlar", 1)[0]


def test_numeric_fact_count_has_a_fixed_upper_bound() -> None:
    frame = pd.DataFrame({f"value_{index}": [index, index + 1] for index in range(14)})
    facts = build_narration_facts(frame, max_numeric_columns=4)

    assert facts.omitted_numeric_columns == 10
    assert facts.text.count("Gözlenen uçlar:") == 4
    assert "ayrıntılandırılmayan sayısal sütun: 10" in facts.text
