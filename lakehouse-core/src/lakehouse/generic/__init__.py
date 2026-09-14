"""Generic tabular ingestion for data nobody wrote a connector for."""

from .connector import ADHOC_SOURCE_ID, GenericTabularConnector
from .formats import SUPPORTED_FORMATS, FormatError, resolve_format
from .parser import GENERIC_SCHEMA_VERSION, GenericTabularParser
from ._access import AccessDeniedError, LocalFilePolicy

__all__ = [
    "ADHOC_SOURCE_ID",
    "GENERIC_SCHEMA_VERSION",
    "SUPPORTED_FORMATS",
    "AccessDeniedError",
    "FormatError",
    "GenericTabularConnector",
    "GenericTabularParser",
    "LocalFilePolicy",
    "resolve_format",
]
