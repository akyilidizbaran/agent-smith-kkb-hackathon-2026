"""Single allow-list and canonical identity for generic parser choices.

Only these scalar choices enter durable provenance. Unknown keys and values are refused
without echoing their contents (which may be credentials).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .formats import FormatError

ENCODINGS = ("utf-8-sig", "utf-8", "cp1254", "latin-1")
_DEFAULTS = {
    "csv": {"delimiter": None, "encoding": "auto"},
    "tsv": {"delimiter": None, "encoding": "auto"},
    "json": {"records_field": None, "encoding": "auto"},
    "xlsx": {"sheet_name": None},
    "html": {"table_index": None, "encoding": "auto"},
}


def canonical_parser_config(resolved: str, parameters: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(resolved, str) or resolved not in _DEFAULTS or not isinstance(parameters, dict):
        raise FormatError("unsupported parser configuration")
    defaults = _DEFAULTS[resolved]
    if set(parameters) - (set(defaults) | {"format"}):
        raise FormatError("unknown or format-inapplicable parser parameter; use the format allow-list")
    if "format" in parameters:
        requested = parameters["format"]
        if not isinstance(requested, str) or requested.strip().lower() != resolved:
            raise FormatError("parser format must match resolved_format")
    config = {**defaults, **parameters, "format": resolved}
    for key, value in config.items():
        if key == "delimiter" and value is not None:
            if not isinstance(value, str) or value not in (",", ";", "\t", "|"):
                raise FormatError("delimiter must be one of comma, semicolon, tab or pipe")
        elif key == "encoding":
            if not isinstance(value, str) or value not in (*ENCODINGS, "auto"):
                raise FormatError("encoding must be auto, utf-8-sig, utf-8, cp1254 or latin-1")
        elif key in {"sheet_name", "records_field"} and value is not None:
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise FormatError("sheet_name/records_field must be a non-empty string of at most 256 characters")
        elif key == "table_index" and value is not None:
            if type(value) is not int or value < 0:
                raise FormatError("table_index must be a non-negative integer")
    return config


def parser_config_hash(config: dict[str, Any]) -> str:
    canonical = canonical_parser_config(config.get("format"), config)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def config_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    config = metadata.get("parser_config")
    canonical = canonical_parser_config(metadata.get("resolved_format"), config)
    if config != canonical or metadata.get("parser_config_sha256") != parser_config_hash(canonical):
        raise FormatError("artifact parser configuration or hash is not canonical")
    return canonical
