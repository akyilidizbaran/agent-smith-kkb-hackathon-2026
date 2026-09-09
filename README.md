# AgentSmithler — Data/Lakehouse çalışma dalları

Bu dal ailesi KKB Agentic Data Analytics Hackathon projesinin **Data/Lakehouse**
katmanını geliştirir. Amaç; BDDK ve TCMB/EVDS gibi kaynaklardan alınan veriyi
değişmez, test edilebilir ve kaynağı gösterilebilir biçimde hazırlayıp agent
katmanına güvenli bir SQL yüzeyi sunmaktır.

> GitHub ana sayfası varsayılan olarak `main` dalını gösterir. Aşağıdaki çalışmalar
> feature dallarında yürütülmektedir; kodu görmek için sol üstteki branch seçicisinden
> ilgili dalı seçin veya dalın açıklama sayfasını açın.

## Elif'in çalışma dalları

| Dal | Amaç | Durum | Ayrıntı |
|---|---|---|---|
| `feature/lakehouse-source-access` | EVDS ve BDDK Aylık verisini güvenli biçimde RAW/Bronze sınırına getirmek | Tamamlandı ve integration'a alındı | [Source Access](lakehouse-core/docs/branches/lakehouse-source-access.md) |
| `feature/source-access-bddk-weekly` | BDDK Haftalık için doğrulanmış connector/parser akışı oluşturmak | Tamamlandı ve integration'a alındı | [BDDK Haftalık](lakehouse-core/docs/branches/source-access-bddk-weekly.md) |
| `feature/lakehouse-metadata-catalog` | Serilerin anlamını, birimini ve toplama kurallarını `meta.series` içinde tutmak | Tamamlandı ve integration'a alındı | [Metadata Catalog](lakehouse-core/docs/branches/lakehouse-metadata-catalog.md) |
| `feature/source-access-hardening` | Kaynak kimliği, TLS hata sınıflaması ve ikinci EVDS serisiyle Source Access'i sağlamlaştırmak | Tamamlandı ve integration'a alındı | [Source Access Hardening](lakehouse-core/docs/branches/source-access-hardening.md) |
| `feature/lakehouse-integration` | Altyapı, kaynak erişimi ve semantic catalog çalışmalarını birlikte doğrulamak | Güncel ortak çalışma dalı | [Integration](lakehouse-core/docs/branches/lakehouse-integration.md) |

## Güncel akış

```text
BDDK / EVDS
    ↓ Connector
Değişmez RAW + SHA-256 + request/artifact provenance
    ↓ Parser
Bronze Parquet
    + meta.series semantic catalog
    ↓
Silver  ← sıradaki aktif aşama
    ↓
Gold
    ↓
Agent'ın güvenli SQL yüzeyi
```

Güncel birleşik sürümde 357 test, build ve offline demo kontrolü geçmiştir.
Silver/Gold ve agent teslim yüzeyi sonraki aşamalardır.

## Neden bu kadar ayrı dal var?

- Kaynak erişimi ile veri yorumunu birbirine karıştırmamak için.
- Aynı anda çalışan ekip üyelerinin dosya çakışmasını azaltmak için.
- Her kararın, fixture'ın ve testin hangi çalışmada eklendiğini izleyebilmek için.
- Bir kaynak bozulduğunda hatanın connector, parser, katalog veya dönüşüm
  katmanlarından hangisinde olduğunu kolayca bulabilmek için.

Projenin kurulum ve komutları için [lakehouse-core README](lakehouse-core/README.md)
dosyasına bakın.
