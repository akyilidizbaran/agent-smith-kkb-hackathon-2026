"""DomainProfile — motorun alan bilgisini koddan ayıran katman.

Şartname platformun jenerik olmasını, "içi boşaltılıp bambaşka bir sağlık
verisiyle de çalışabilir" olmasını istiyor. Mimari (contract, registry, adapter)
zaten alan-bağımsızdı; ancak MODELE GİDEN METİNLER finansa çakılıydı:
system prompt'ta "Türkiye ekonomisi ve bankacılık verileri", araç şemalarında
"ör. 'konut kredisi'", hatta bir tablo adı. Bunlar yorum değil, her turda
prompt'a giren içerik.

Bu modül o metinleri şablonlaştırır. Profil ya elle yazılır ya da katalogdan
DETERMİNİSTİK olarak türetilir.

Neden modelle tahmin etmiyoruz: EMNLP 2024 Findings (4 model ailesi, 2.410 soru,
162 rol) system prompt'a persona eklemenin performansı iyileştirmediğini, ayrıca
"en iyi rolü seçme" stratejilerinin rastgele rol seçmekten daha iyi olmadığını
gösteriyor. Ölçülebilir kazanç rolde değil, veri bağlamında. Ayrıntı: ADR-0012.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts.catalog import DatasetSpec

# Şablonlarda kullanılan yer tutucular. str.format değil düz değiştirme
# kullanıyoruz: örnek metinlerde SQL süslü parantezleri geçebiliyor.
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


# Kanonik adlarda sık geçen ayırıcılar. "A - B" biçiminde bir adın ayırt edici
# kısmı genellikle sonuncu parçadır ("Tüketici Kredileri - Konut" -> "Konut").
_AYIRICI = re.compile(r"\s*[-–—:/|]\s*")


def kisa_terim(deger: str, max_uzunluk: int = 24) -> str:
    """Kanonik bir değerden, arama örneği olarak kullanılabilecek kısa terim üretir.

    İki yerde kullanılıyor: profil örnekleri ve `lakehouse_distinct_values`'ın
    daraltma önerisi. Tek kaynakta tutuluyor ki ikisi ayrışmasın.
    """
    parcalar = [p.strip() for p in _AYIRICI.split(deger) if p.strip()]
    aday = parcalar[-1] if parcalar else deger.strip()
    # Parantezli ekleri at: "Konut (Dövize Endeksli)" -> "Konut"
    aday = re.sub(r"\s*\(.*?\)\s*", " ", aday).strip()
    return aday if 0 < len(aday) <= max_uzunluk else deger[:max_uzunluk].strip()


@dataclass(frozen=True)
class DomainProfile:
    """Motorun hangi alanda çalıştığını anlatan, çalışma anında sabit bilgi.

    Runtime'da sınıflandırma YOK: lakehouse'a ne yüklüyse alan odur ve bu
    deploy anında bellidir. Her soruda yeniden karar vermek, cevabı zaten
    bilinen bir soruyu tekrar sormak olurdu.
    """

    domain: str = "yapılandırılmış veri"
    audience: str = "veri analisti"

    # Araç açıklamalarındaki örneklerde kullanılır. Somut örnek, soyut
    # açıklamadan daha iyi çalışıyor; ama örneğin alanı koda gömülmemeli.
    example_table: str = "bir_tablo"
    example_time_column: str = "donem"
    example_category_column: str = "kategori"
    example_measure: str = "deger"
    example_entity: str = "bir kalem"

    def render(self, text: str) -> str:
        """Metindeki yer tutucuları profil değerleriyle doldurur.

        Tanınmayan yer tutucu olduğu gibi bırakılır — SQL örneklerindeki
        süslü parantezler bozulmasın diye.
        """
        values = {
            "domain": self.domain,
            "audience": self.audience,
            "example_table": self.example_table,
            "example_time_column": self.example_time_column,
            "example_category_column": self.example_category_column,
            "example_measure": self.example_measure,
            "example_entity": self.example_entity,
        }
        return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)

    # ------------------------------------------------------------------
    @classmethod
    def generic(cls) -> DomainProfile:
        """Hiçbir alan bilgisi olmayan varsayılan. Motor bununla da çalışır."""
        return cls()

    @classmethod
    def from_catalog(
        cls,
        datasets: list[DatasetSpec],
        *,
        domain: str | None = None,
        audience: str | None = None,
    ) -> DomainProfile:
        """Profili katalogdan deterministik olarak türetir.

        Katalog alanı zaten taşıyor: kaynak adı, etiketler, kolon rolleri ve
        örnek değerler orada. Yeni bir veri seti yüklendiğinde profil
        kendiliğinden ona uyar — jenerikliğin somut kanıtı budur.

        `domain` ve `audience` elle verilebilir; bunlar üsluba dair tercihler
        ve katalogdan güvenilir biçimde çıkarılamaz.
        """
        if not datasets:
            return cls.generic()

        from .contracts.catalog import ColumnRole

        # En zengin katalog kaydını örnek kaynağı olarak seç: en çok kolonu
        # olan tablo, alanı en iyi temsil eden tablodur.
        spec = max(datasets, key=lambda s: len(s.columns))

        sources = sorted({s.source for s in datasets if s.source})
        derived_domain = domain or (
            f"{' ve '.join(sources)} kaynaklı veriler" if sources else cls.domain
        )

        measures = [c for c in spec.columns if c.role == ColumnRole.MEASURE]
        dimensions = [c for c in spec.columns if c.role == ColumnRole.DIMENSION]

        # Örnek varlık: kullanıcının YAZACAĞI gibi kısa bir arama terimi olmalı,
        # kaynaktaki kanonik tam ad değil. Ölçülmüş sebep: `example_entity` tam ad
        # olarak türetildiğinde ("Tüketici Kredileri - Konut") model bunu
        # `contains` filtresine birebir yazdı, sonuç boş döndü ve golden set
        # 5/7'den 1/7'ye düştü. Örneğin gerçek olması yetmiyor, İYİ olması gerek.
        entity = cls.example_entity
        for dim in dimensions:
            if dim.example_values:
                entity = kisa_terim(dim.example_values[0])
                break
        else:
            if spec.tags:
                entity = spec.tags[0]

        return cls(
            domain=derived_domain,
            audience=audience or cls.audience,
            example_table=spec.dataset_id,
            example_time_column=spec.time_column,
            example_category_column=dimensions[0].name if dimensions else cls.example_category_column,
            example_measure=measures[-1].name if measures else cls.example_measure,
            example_entity=entity,
        )
