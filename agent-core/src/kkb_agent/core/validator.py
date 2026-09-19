"""Sınır doğrulayıcı — her araç çağrısı aynı boru hattından geçer.

    şema → SQL guard → referans → politika → run

Bu dört kontrol daha önce de vardı; beş dosyaya dağılmıştı (`registry.py`,
`tool.py`, `tools/lakehouse.py`, `tools/workspace.py`, `agent.py`). Davranış
değişmiyor, adres değişiyor: "Validator nerede?" sorusunun cevabı artık bu dosya.
Mesaj metinleri olduğu gibi taşındı — ölçülerek yazıldılar (ADR-0010/0016/0017/0019).

Sıranın gerekçesi:
- **Şema önce.** Pydantic'ten geçmeyen argümanın referansı da politikası da yok.
- **SQL guard referanstan önce.** Yasak bir ifadenin referanslarını doğrulamak
  anlamsız; "dönem filtresi ekle" deyip DROP'u yeniden denetmek bir tur yakar.
- **Referans politikadan önce.** Var olmayan bir seri için dönem politikası
  konuşulmaz.
- **Politika en son.** Referansları sağlam bir çağrının yine de çalışmaması
  gereken hâlleri: dönem filtresi yok, sorulan ay kapsam dışı, ifade güvensiz.

Aracın kendisi yalnız `validate_refs` ve `check_policy` hook'larını bildirir;
sıralamayı ve hataya sarmayı burası yapar. Yeni bir araç bu iki hook'u yazar,
başka bir şey öğrenmez. Tasarım Büşra'nın V3 `BoundaryValidator`'ından (§3.3)
alındı; ortak katmana taşındı ki tek kopya olsun.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from ..adapters.duckdb_lakehouse import guard_sql
from ..contracts.lakehouse import LakehouseError
from .errors import ToolError
from .tool import Tool, ToolResult

log = logging.getLogger(__name__)


class BoundaryValidator:
    """Araç çağrısını katman katman doğrular; geçerse çalıştırır."""

    def validate(
        self, tool: Tool, raw_args: dict[str, Any]
    ) -> tuple[BaseModel | None, ToolError | None]:
        """Doğrulanmış parametreler ya da ilk takılan katmanın hatası."""

        normalizer = getattr(tool, "normalize_args", None)
        if callable(normalizer):
            raw_args = normalizer(raw_args)

        # 1. şema — argümanın şekli
        try:
            params = tool.Params(**raw_args)
        except Exception as exc:  # noqa: BLE001 — Pydantic ve bozuk JSON (__raw__) birlikte
            props = list(tool.Params.model_json_schema().get("properties", {}))
            return None, ToolError(
                error_code="INVALID_ARGS",
                message=f"'{tool.name}' aracının parametreleri geçersiz: {exc}",
                hint=f"Beklenen alanları doldur: {', '.join(props)}",
                candidates=props,
                layer="schema",
            )

        # 2. SQL guard — `sql` alanı taşıyan her araç için, aracın kendisinden bağımsız.
        # Adaptör de aynı guard'ı çalıştırır (ADR-0020, savunma derinliği); burada
        # yakalamak turu erken bitirir ve hatayı doğru sınıfa (politika) yazar.
        sql = getattr(params, "sql", None)
        if isinstance(sql, str):
            try:
                guard_sql(sql)
            except LakehouseError as exc:
                return params, ToolError(
                    error_code="UNSAFE_SQL",
                    message=str(exc),
                    hint=None,
                    layer="policy",
                    retryable=False,
                )

        # 3. referans — argüman var olan bir şeye mi işaret ediyor
        try:
            err = tool.validate_refs(params)
        except LakehouseError as exc:
            err = ToolError(error_code="DATASET_NOT_FOUND", message=str(exc), layer="reference")
        if err is not None:
            return params, err

        # 4. politika — referansı sağlam çağrının yine de çalışmaması gereken hâli
        err = tool.check_policy(params)
        if err is not None:
            return params, err
        return params, None

    def validate_and_run(self, tool: Tool, raw_args: dict[str, Any]) -> ToolResult:
        params, err = self.validate(tool, raw_args)
        if err is not None:
            log.info("validator %s/%s: %s", tool.name, err.layer, err.error_code)
            return ToolResult(content=err.render(), ok=False, error=err)
        assert params is not None
        try:
            return tool.run(params)
        except Exception as exc:  # noqa: BLE001 — araç istisnası modele okunabilir döner
            log.exception("araç istisnası: %s", tool.name)
            return ToolResult.fail(
                "TOOL_FAILED",
                f"'{tool.name}' çalışırken hata: {type(exc).__name__}: {exc}",
                layer="harness",
            )


DEFAULT_VALIDATOR = BoundaryValidator()

__all__ = ["BoundaryValidator", "DEFAULT_VALIDATOR"]
