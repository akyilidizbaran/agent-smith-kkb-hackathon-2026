# Lakehouse Contract — veri katmanı ↔ agent katmanı sözleşmesi

> Bu doküman **veri ekibi (3 kişi)** ile **agent ekibi** arasındaki arayüzü tanımlar.
> Amaç: iki ekibin birbirini beklemeden paralel çalışabilmesi.

## Neden sözleşme?

Agent katmanı Lakehouse'un nasıl kurulduğunu bilmez. Parquet + Iceberg, Delta ya da düz
DuckDB — agent açısından fark etmez. Agent yalnızca aşağıdaki iki şeye bakar:

1. **`LakehouseClient`** arayüzü (`src/kkb_agent/contracts/lakehouse.py`)
2. **`DatasetSpec`** semantic catalog şeması (`src/kkb_agent/contracts/catalog.py`)

Bu ayrım aynı zamanda yarışmanın *"platform jenerik olmalı, içi boşaltılıp bambaşka bir
sağlık verisiyle de çalışabilmeli"* şartını mimari düzeyde karşılar: yeni bir alana geçmek
için sadece yeni bir `LakehouseClient` uygulaması + yeni katalog yazılır, agent kodu aynı kalır.

---

## 1. Uygulanması gereken arayüz

```python
class LakehouseClient(Protocol):
    def list_datasets(self) -> list[DatasetSpec]: ...
    def get_dataset(self, dataset_id: str) -> DatasetSpec: ...
    def search_datasets(self, query: str, limit: int = 5) -> list[DatasetSpec]: ...
    def execute_sql(self, sql: str, *, max_rows: int = 10_000) -> QueryResult: ...
    def preview(self, dataset_id: str, n: int = 5) -> QueryResult: ...
    def health(self) -> dict[str, Any]: ...
```

`Protocol`'ü miras almanız gerekmez — aynı imzalara sahip bir sınıf yeterlidir.

**`execute_sql` için iki şart:**
- Salt okunur olmalı; `INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/ATTACH/COPY` reddedilmeli.
- Dönen `QueryResult`, `QueryProvenance` içermeli (SQL, kaynak adı, kaynak URL, satır sayısı,
  uyarılar). Bu, slayttaki **"Güven katmanı: Kaynak gösterimi – İzlenebilirlik – Doğruluk
  Kontrolü"** maddesinin karşılığıdır ve puanlanacaktır.

---

## 2. Semantic Catalog — en kritik kısım

Ham şema (tablo + kolon adı) bir LLM için **yetersizdir**. Bir sayının stok mu akım mı
olduğunu, hangi çarpanla saklandığını, kümülatif olup olmadığını bilmeden doğru SQL
üretilemez. Her Gold tablo kendini `DatasetSpec` ile tanıtmalıdır.

### Doldurulması zorunlu alanlar ve neden

| Alan | Neden kritik |
|---|---|
| `description` | Agent'ın tablo seçimi büyük ölçüde bu metne dayanır. Türkçe ve açıklayıcı yazın. |
| `frequency` | Frekans hizalamanın girdisi. |
| `time_column`, `grain` | Bir satırı benzersiz kılan kolonlar; join ve mükerrer sayım kontrolü. |
| `coverage` | Agent, kapsam dışı bir dönem sorulduğunda **uydurmak yerine** "bu veri yok" demeli. |
| `notes` | Analizi bozabilecek uyarılar (alt toplam satırları, birim değişimi vb.). |

### `ColumnSpec` — dikkat edilecek dört alan

**`semantic_type`** — frekans dönüşümünde hangi kuralın uygulanacağını belirler.
Yanlış seçilirse aylık→çeyreklik dönüşümler **sessizce** yanlış sonuç verir:

| Değer | Anlamı | Frekans dönüşümünde |
|---|---|---|
| `stock` | belirli bir andaki bakiye (kredi stoku) | dönem **sonu** değeri |
| `flow` | dönem içi akım (kullandırım, ciro) | **toplanır** |
| `rate` | oran/faiz (%) | ağırlıklı ortalama |
| `index` | endeks (TÜFE, konut fiyat endeksi) | dönem sonu ya da ortalama |
| `ratio` | pay/yüzde (NPL oranı) | **yeniden hesaplanmalı**, ortalaması alınmaz |
| `count` | adet (şube sayısı) | stok gibi |

**`cumulative`** — BDDK slaytındaki uyarının doğrudan karşılığı:
*"bazı veriler paylaşım başlangıcından itibaren kümülatif giderken, bazıları yıllık bazda
kümülatif gitmektedir."* İki farklı rejim var, ikisi farklı ayrıştırma ister:
- `ytd` → yıl içinde ardışık fark; yılın ilk dönemi olduğu gibi kalır
- `since_inception` → düz fark
- `none` → değer zaten o döneme ait

**`unit` + `unit_multiplier`** — Canlı doğrulanmış örnek: BDDK aylık bülteninde
**Tablo 3/4 "milyon TL", Tablo 5 "bin TL"** yayınlıyor. Agent her zaman gerçek birimle
konuşmalı; çarpan katalogda tutulur (`milyon TL` için `1e6`).

**`aliases`** — Agent'ın kolon seçimindeki isabet oranını **en çok** bu alan belirler.
Kullanıcı "mortgage", "ev kredisi", "konut kredisi" diyebilir; hepsini yazın.

---

## 3. Sizden beklediğim çıktı sırası

Agent tarafını bloke etmemek için bu sırayı öneriyorum:

1. **Önce katalog, sonra veri.** Tek bir tablo için doldurulmuş bir `DatasetSpec` ve
   birkaç yüz satır örnek veri, agent'ı geliştirmem için yeterli. Tüm 5 yıllık veriyi
   beklemem gerekmiyor.
2. **Tablo adları katalogdaki `dataset_id` ile birebir aynı olsun.** Agent SQL'i bu ada göre yazar.
3. **Gold katman "geniş" değil "uzun" olsun.** Yani `donem, kalem, deger` gibi; her yeni
   kırılım için yeni kolon açmak yerine satır ekleyin. Agent'ın pivotlaması kolaydır,
   bilinmeyen kolon adı tahmin etmesi zordur.

## 4. Referans uygulama

`src/kkb_agent/adapters/duckdb_lakehouse.py` bu sözleşmenin çalışan bir uygulamasıdır
(DuckDB + JSON katalog). `scripts/dev_seed.py` ise gerçek BDDK verisiyle nasıl
doldurulduğunu gösterir. İkisi de sizin üretim çözümünüz hazır olunca **atılacaktır**;
referans olarak bakabilirsiniz.

## 5. BDDK erişimi hakkında (canlı doğrulandı, 2026-09-08)

Excel indirip parse etmeye gerek yok — BDDK'nın kimlik doğrulama istemeyen JSON
endpoint'leri var:

```
POST https://www.bddk.org.tr/BultenAylik/tr/Home/BasitRaporGetir
  body: tabloNo, yil, ay, paraBirimi=TL|USD, taraf
POST https://www.bddk.org.tr/BultenFinturk/tr/Home/VeriGetir
  body: tabloNo, donem, tarafList[], sehirList[]
POST https://www.bddk.org.tr/BultenHaftalik/tr/Home/KiyaslamaJsonGetir
  body: dil, tarih, id, parabirimi, sutun, tarafKodu, gun
```

`taraf` kodları: `10001` Sektör, `10002` Mevduat, `10003` Katılım,
`10004` Kalkınma ve Yatırım, `10005` Yerli Özel, `10006` Kamu, `10007` Yabancı.

Aylık bülten tablo haritası (doğrulandı): `1` Bilanço, `2` Kar/Zarar, `3` Krediler,
`4` Tüketici Kredileri, `5` Sektörel Kredi Dağılımı **(bin TL!)**, `6` KOBİ Kredileri,
`9`/`10` Mevduat, `12` Sermaye Yeterliliği, `15` Rasyolar.

⚠️ BDDK'nın SSL sertifika zinciri eksik; `httpx.Client(verify=False)` ya da uygun CA
bundle gerekiyor.

⚠️ Alt toplam satırlarına dikkat: `Tüketici Kredileri (2+3+4)` bir toplamdır, alt
kalemlerle birlikte toplanırsa mükerrer sayım olur. `notes` alanına yazın.
