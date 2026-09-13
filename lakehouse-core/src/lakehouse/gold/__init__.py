"""Gold P0: parameterized transformations over Silver, driven by the semantic catalog.

Gold is a set of **functions**, not a set of tables. A table only answers questions about the
series it was built for; a function applies the catalog's rule to whatever series it is handed,
including one the jury brings on the day. Nothing here materializes anything: these functions
read ``silver.fact_observation`` and ``meta.series`` and return DataFrames.

Three guarantees hold across all of them:

1. **The catalog decides how numbers combine.** ``measure_type``, ``default_agg``,
   ``week_anchor``, the source frequency and ``semantic_confidence`` are read from
   ``meta.series`` at call time. No caller and no model can supply or override them.
2. **Fail-closed.** When the meaning of a transformation is not established -- unverified
   semantics, a measure type with no safe rule, upsampling, or two vintages for one period --
   the call raises a :class:`~lakehouse.gold.errors.GoldError` naming the reason, instead of
   returning a plausible number.
3. **Read-only.** Only parameterized ``SELECT`` statements are issued, so these functions run
   unchanged on the hardened read-only connection the agent layer uses.

See ``docs/gold-contract.md`` for the full behaviour matrix.

**Materialization (P1)** does not change the above. ``catalog/gold/*.yml`` names reviewed
calls of these functions; ``python -m lakehouse gold`` caches each as ``gold.<metric_id>``
with build provenance on every row and records refusals in ``meta.gold_build``
(:mod:`lakehouse.gold.build`). ``python -m lakehouse gold-run`` runs one call read-only for a
caller in another process (:mod:`lakehouse.gold.serialize`).
"""

from .align import ALIGNED_COLUMNS, GOLD_QUALITY_FLAGS, align_frequency
from .build import (
    GOLD_BUILD_TABLE,
    PROVENANCE_COLUMNS,
    GoldBuildReport,
    MetricBuildOutcome,
    build_gold_tables,
    call_gold_function,
    silver_fingerprint,
)
from .catalog import (
    DEFAULT_GOLD_CATALOG_ROOT,
    GOLD_FUNCTIONS,
    GoldCatalogError,
    GoldMetricRecord,
    load_gold_catalog_files,
)
from .cumulative import DECOMPOSED_COLUMNS, DECOMPOSITION_FLAGS, decompose_cumulative
from .errors import GOLD_REFUSAL_REASONS, GoldError, GoldRefusal
from .join import JOIN_KEY_COLUMNS, column_key, join_on_period
from .periods import TARGET_FREQUENCIES

__all__ = [
    "ALIGNED_COLUMNS",
    "DEFAULT_GOLD_CATALOG_ROOT",
    "GOLD_BUILD_TABLE",
    "GOLD_FUNCTIONS",
    "GoldBuildReport",
    "GoldCatalogError",
    "GoldMetricRecord",
    "MetricBuildOutcome",
    "PROVENANCE_COLUMNS",
    "build_gold_tables",
    "call_gold_function",
    "load_gold_catalog_files",
    "silver_fingerprint",
    "DECOMPOSED_COLUMNS",
    "DECOMPOSITION_FLAGS",
    "GOLD_QUALITY_FLAGS",
    "GOLD_REFUSAL_REASONS",
    "JOIN_KEY_COLUMNS",
    "TARGET_FREQUENCIES",
    "GoldError",
    "GoldRefusal",
    "align_frequency",
    "column_key",
    "decompose_cumulative",
    "join_on_period",
]
