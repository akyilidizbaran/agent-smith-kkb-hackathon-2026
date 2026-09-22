"""Generic user-facing labels for technical lakehouse columns."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from kkb_agent.contracts.catalog import ColumnRole
from kkb_agent.contracts.lakehouse import QueryProvenance
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.labels import display_column_labels, rename_frame_columns


def test_gold_column_labels_use_catalog_semantics_and_keep_internal_names_out_of_view() -> None:
    technical = "bddk_monthly:1536_Toplam@bddk:10001::value"
    changed = technical + "_change"
    frame = pd.DataFrame({
        "period_end": pd.to_datetime(["2022-01-31", "2022-02-28"]),
        technical: [100.0, 110.0],
        changed: [None, 10.0],
    })
    workspace = AnalysisWorkspace()
    provenance = QueryProvenance(sql="SELECT", dataset_ids=["bddk_monthly:1536_Toplam"])
    workspace.set_table(frame, description="gold fixture", column_provenance={technical: provenance, changed: provenance})
    spec = SimpleNamespace(
        dataset_id="bddk_monthly:1536_Toplam",
        name="Tüketici Kredileri - İhtiyaç, Toplam (Sektör)",
        columns=[SimpleNamespace(role=ColumnRole.MEASURE, name="value", aliases=["ihtiyaç kredisi"], unit="TRY_mn")],
    )

    labels = display_column_labels(frame, workspace=workspace, specs=[spec])
    renamed = rename_frame_columns(frame, labels)

    assert labels["period_end"] == "Dönem"
    assert labels[technical] == "ihtiyaç kredisi (milyon TL)"
    assert labels[changed] == "ihtiyaç kredisi — değişim (milyon TL)"
    assert list(renamed.columns) == ["Dönem", "ihtiyaç kredisi (milyon TL)", "ihtiyaç kredisi — değişim (milyon TL)"]
    assert list(frame.columns)[1] == technical, "etiketleme workspace kolon kimliğini değiştirmez"
