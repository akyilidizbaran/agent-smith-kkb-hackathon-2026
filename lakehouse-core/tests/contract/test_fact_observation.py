"""Contract tests for the frozen Silver V1 fact_observation schema."""

from pathlib import Path

import yaml


CONTRACT_PATH = Path("schemas/fact_observation.yml")
EXPECTED_FIELDS = [
    "series_id",
    "entity_id",
    "observation_date",
    "period_start",
    "period_end",
    "value",
    "frequency",
    "unit",
    "measure_type",
    "quality_flag",
    "source_id",
    "dataset_id",
    "artifact_sha256",
    "fetched_at",
    "schema_version",
    "vintage_id",
    "run_id",
]


def _contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_fact_observation_has_the_frozen_v1_field_order() -> None:
    fields = _contract()["fields"]
    assert [field["name"] for field in fields] == EXPECTED_FIELDS


def test_fact_observation_types_and_nullability_match_v1() -> None:
    fields = {field["name"]: field for field in _contract()["fields"]}

    expected_types = {
        "series_id": "string",
        "entity_id": "string",
        "observation_date": "date",
        "period_start": "date",
        "period_end": "date",
        "value": "float",
        "frequency": "string",
        "unit": "string",
        "measure_type": "string",
        "quality_flag": "string",
        "source_id": "string",
        "dataset_id": "string",
        "artifact_sha256": "string",
        "fetched_at": "timestamp_utc",
        "schema_version": "string",
        "vintage_id": "string",
        "run_id": "uuid",
    }
    expected_nullable = {
        "series_id": False,
        "entity_id": True,
        "observation_date": False,
        "period_start": True,
        "period_end": True,
        "value": True,
        "frequency": False,
        "unit": False,
        "measure_type": False,
        "quality_flag": False,
        "source_id": False,
        "dataset_id": False,
        "artifact_sha256": False,
        "fetched_at": False,
        "schema_version": False,
        "vintage_id": True,
        "run_id": True,
    }

    assert {name: field["type"] for name, field in fields.items()} == expected_types
    assert {name: field["nullable"] for name, field in fields.items()} == expected_nullable
    assert "date_key" not in fields


def test_fact_observation_has_only_generic_fields_and_small_quality_vocabulary() -> None:
    contract = _contract()
    field_names = {field["name"] for field in contract["fields"]}
    forbidden = {
        "chart_id",
        "kalem_id",
        "column_label",
        "series_column",
        "measure_column",
        "raw_path",
        "locator",
        "request_metadata_json",
        "housing_loan_balance",
    }

    assert field_names.isdisjoint(forbidden)
    assert contract["quality_flag_vocabulary"] == [
        "ok",
        "missing_value",
        "source_warning",
    ]
