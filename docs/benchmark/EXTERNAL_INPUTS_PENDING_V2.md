# V2 harici girdi bekleyen vakalar

Kanonik V2 manifestinde harici bağımlılıkların güncel sayısı **44**: **38 fixture/snapshot** ve **6 canlı web**. Bu liste, kullanıcı CSV/XLSX veya URL değerleri gelmeden sayı yazılmaması gereken vakaları gösterir. 27 sayısı önceki ara kapsamın sayısıdır; manifestteki açık `external_mode` alanı güncel kaynaktır.

## Fixture / snapshot (38)

| ID | Placeholder | Gerekli girdi |
|---|---|---|
| **J01** | `{{FAIZ_ORANI_XLSX}}`, `{{KREDI_BAKIYE_CSV}}` | İki kullanıcı tablosu anahtarla birleştirme |
| **J02** | `{{IL_TABLE_A}}`, `{{IL_TABLE_B}}` | İl ve dönem anahtarı |
| **J03** | `{{UNIT_FILE_CSV}}` | Kaynaklar arası birim eşleme |
| **J04** | `{{DATE_FILE_ISO}}`, `{{DATE_FILE_YYYYMM}}` | Farklı tarih biçimleri |
| **J05** | `{{WIDE_MONTHS_CSV}}` | Geniş ve uzun format |
| **J06** | `{{FINTURK_IL_FILE}}` | Üç kaynaklı karşılaştırma |
| **F05** | `{{LARGE_MONTHLY_CSV}}` | Başarısız ilk tur sonrası devam |
| **E01** | `{{REFERENCE_CSV}}` | CSV ile referans karşılaştırma |
| **E02** | `{{REFERENCE_XLSX}}` | XLSX çoklu sayfa |
| **E03** | `{{CSV_FILE}}`, `{{XLSX_FILE}}` | CSV/XLSX çelişkisi |
| **E04** | `{{PUBLIC_DATA_URL}}` | Harici URL'den aylık veri |
| **E05** | `{{TCMB_TODAY_XML_URL}}` | TCMB günlük kur serisi |
| **E06** | `{{REFERENCE_XLSX}}` | Harici dosya ile hesap kontrolü |
| **E07** | `{{DRIFTED_CSV}}` | Şema drift'i |
| **E08** | `{{GAPPED_XLSX}}` | Harici dosyada eksik dönem |
| **Q06** | `{{TEMPORARILY_UNAVAILABLE_URL}}` | Kaynak erişilemiyor |
| **Q07** | `{{UNTRUSTED_CSV}}` | Prompt injection içeren dosya |
| **U01** | `{{HEALTH_FIXTURE}}` | Sağlık |
| **U02** | `{{ENERGY_FIXTURE}}` | Enerji |
| **U03** | `{{RETAIL_FIXTURE}}` | Perakende |
| **U04** | `{{LOGISTICS_FIXTURE}}` | Lojistik |
| **U05** | `{{EDUCATION_FIXTURE}}` | Eğitim |
| **U06** | `{{TABLE_A}}`, `{{TABLE_B}}` | İki yeni tablo |
| **D06** | `{{CHANGE_POINT_FIXTURE}}` | Çoklu kırılma ve minimum segment |
| **C08** | `{{SHORT_SERIES}}` | Sonuç üretmek için yetersiz örneklem |
| **W02** | `{{UNKNOWN_PUBLIC_URL}}` | URL şema keşfi |
| **W03** | `{{PAGINATED_TABLE_URL}}` | HTML tablo + pagination |
| **W04** | `{{REDIRECTING_URL}}` | Redirect ve kaynak kimliği |
| **W05** | `{{MUTABLE_URL}}` | Kaynak değişmişse drift |
| **I01** | `{{NEW_DOMAIN_CSV}}` | Yeni CSV'yi RAW -> Bronze -> Silver -> Gold |
| **I02** | `{{NEW_DOMAIN_CSV}}` | Idempotent re-ingest |
| **I03** | `{{SALES_V1}}`, `{{SALES_V2}}` | Aynı isim farklı içerik |
| **I04** | `{{SCHEMA_V2}}` | Schema evolution |
| **I05** | `{{CORRUPT_XLSX}}` | Bozuk dosyada partial ingest yapmama |
| **I06** | `{{NEW_DOMAIN_CSV}}` | Analyst/Architect sınırı |
| **S04** | `{{RELEASE_DATE_FIXTURE}}` | Yayın tarihi ile gözlem tarihi ayrımı |
| **S07** | `{{FAILING_WEB_URL}}` | Tool-loop koruması |
| **S08** | `{{CLIMATE_FIXTURE}}` | Tam jeneriklik testi |

## Canlı web snapshot (6)

| ID | Girdi |
|---|---|
| **D07** | Anomali sonrası web bağlamı |
| **W01** | Önce lakehouse, sonra web |
| **W06** | Web başarısız, lakehouse başarılı |
| **W07** | İki web kaynağı çelişiyor |
| **W08** | Tool seçimi gerektirmeyen soruda web'e gitmeme |
| **S01** | Faiz düştü, kredi artmadı, dış bağlam |

Girdiler geldiğinde her vaka için erişim zamanı, nihai URL, durum kodu, response/file SHA-256 ve tablo şeması kaydedilecek; dış kaynaktaki değişim `data_drift` olarak işaretlenecek.
