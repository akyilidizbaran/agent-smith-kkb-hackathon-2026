# ADR-0032: Grafik — belirtim veridir, eksen kararı araçta, deterministik denetçi geçmeden dosya yok

**Durum:** Kabul edildi (C1) · **Tarih:** 2026-09-12 · **Sıradaki:** C2 kanıt paneli

## Bağlam
Demo senaryosunun 3. sorusu bir grafik istiyor ve jüri sayıyı tabloda değil grafikte görecek.
Bir grafiğin yanıltma yolları sayıdan fazladır: kesik eksen büyümeyi abartır, iki eksen
ilişkiyi uydurur, log ölçek etiketsizse okuyucu lineer sanır, birimi olmayan başlık "523"ün
ne olduğunu söylemez, uyarılı gözlem işaretsizse eksik veri düz çizgi olur. Bunlar üslup
değil, hata sınıflarıdır. Modele "dikkatli çiz" demek ADR-0010'daki dersle çelişir: seçenek
bırakılan her kararda model bir gün yanlış seçer.

Mentörün çizgisi de aynı: harness güçlü, LLM'e en az iş. Grafik için "en az iş" şudur:
model NE çizileceğini söyler (tür, kolonlar, başlık), NASIL çizileceğini söyleyemez.

## Karar 1 — Belirtim veridir, model belirtim yazmaz
Grafik bir **Vega-Lite belirtimi**dir: JSON, yani okunabilir ve sınanabilir veri. Model
yalnız `chart(chart_type, y_columns, x_column?, title, dual_axis?, log_scale?,
province_column?)` çağırır. Belirtimi inşacı (`charts/spec.py`) kurar ve kuralları inşa
sırasında uygular:

| kural | nereden | nasıl |
|---|---|---|
| stok/akım/adet serisi sıfırdan başlar | kolonun katalog `semantic_type`'ı (workspace provenance → `DatasetSpec`); bilinmiyorsa da sıfır | `scale.zero: true`; yalnız oran/endeks/rasyo muaf |
| birim ve dönem başlıkta | katalog birimi; dönem x kolonunun min→max'ı | `başlık · milyon TL · 2025-01-31 → 2025-12-31` |
| birim bilinmiyorsa AÇIKÇA yazılır | türetilmiş kolon (yüzde değişim) | `birim belirtilmemiş` başlıkta ve eksende; sessiz boşluk yok |
| uyarılı gözlem işaretli | tabloda `quality_flag ≠ ok` varsa | içi boş kırmızı halka katmanı, tooltip'te sebep |
| çift eksen yalnız istenirse | `dual_axis=true` yalnız kullanıcı isterse (araç açıklaması) | `resolve.scale.y independent`; yoksa tek eksen ve **aynı birim** şartı |
| log yalnız istenirse ve etiketli | `log_scale=true` | eksen başlığına `[log ölçek]`; sıfır kuralı askıya |
| ay sonu tarihleri ay kutusuna | Silver'ın dönem sonu etiketi | `timeUnit: yearmonth` — ölçüldü, 31 Ocak düz eksende Şubat çizgisine düşüyordu |
| Vega alan adı güvenliği | `evds:TP.KTF12::value` gibi noktalı kolonlar | gömülü veride güvenli ad, `usermeta.fields`'te asıl ad — ölçüldü, nokta iç içe erişim sayıldı ve faiz çizgisi hiç çizilmedi |

Gold join kolonları (`<seri>@<varlık>::value`) önekten seriye bağlanır: birim ve katalog adı
oradan gelir; öneki tanınmayan kolon başka serinin birimini **miras almaz** (ölçüldü,
alıyordu).

## Karar 2 — Bağımsız deterministik denetçi, fail-closed
`charts/lint.py` aynı belirtimi inşacıdan bağımsız okuyup dokuz kuralı sınar: `level_zero`,
`bar_zero`, `dual_axis_asked`, `log_labelled`, `title_unit_period`, `quality_marked`,
`no_silent_subset` (belirtimdeki satır sayısı = tablodaki; haritada her il bir sınıra
eşleşti), `axis_unit`, `single_unit_axis`. Uygulanmayan kural raporda "uygulanmadı" diye
görünür, sessizce geçmez.

Denetçi geçmezse **dosya yazılmaz**, araç `TOOL_FAILED` ile döner ve rapor kullanıcıya gider.
Neden ayrı dosya: inşacı ile denetçi aynı yerde olsaydı inşacının hatası denetçinin de
hatası olurdu. Testler belirtimi kasıtlı bozar (kesik eksen, atılmış kalite katmanı,
yarım veri, etiketsiz log) ve denetçinin yakaladığını ölçer.

## Karar 3 — Tarayıcısız çizim, harita sınır dosyasına bağlı
PNG/SVG `vl-convert` ile üretilir: yerel Rust çalışma zamanı, ağ yok, tarayıcı yok, Node
yok; ölçüldü **0,36 s**. Belirtim her zaman `.vl.json` olarak yanına yazılır: görüntü
üretilemese de grafik kaybolmaz. Ad = başlık slug'ı + belirtim özeti, deterministik.

Harita (`chart_type=map`) il adlarını normalize eder (`İstanbul`/`ISTANBUL`/`izmir` → tek
anahtar) ve `assets/geo/tr_provinces.geojson` sınırlarıyla eşler; eşleşmeyen il denetçiyi
durdurur (sessiz düşme yok). **Sınır dosyası repoda yok:** dış bir veri dosyasıdır,
kaynağı ve lisansı `assets/geo/README.md`'ye yazılarak kullanıcı onayıyla eklenir. Dosya
yokken araç politika katmanında durur ve çubuk grafik önerir. Aynı sebeple 81 il haritası
golden'ı dosya gelince yazılacak (G10 çizgi grafik).

Dosya yolu cevaba yazılmaz: sistem grafiği cevabın altında ayrıca gösterir (CLI `[grafik]`
satırı, `AgentAnswer.artifacts`). Ölçüldü: model yolu cevaba gömüyordu.

## Ölçüm
- Birim testleri 174 → **201**: inşacı (8), kasıtlı bozuk belirtimlerle denetçi (4), harita
  ve normalizasyon (3), çizim (2), araç (9: aktif tablo yok, olmayan kolon, çift eksen,
  türetilmiş kolonun birimi, sınır dosyası yokken politika, sentetik sınırla harita, denetçi
  geçmeyince dosya yok, Gold join önek çözümü).
- Gerçek veri: 2025 aylık stok çizgisi (12 ay, y=0, başlıkta milyon TL) ve Gold join'den
  çift eksenli bakiye+faiz (24 ay, sol milyon TL, sağ yüzde) — ikisi de görsel olarak
  doğrulandı.
- **Golden G10** ("2025 aylık göster ve çizgi grafiğini çiz"): **3/3 kararlı, 5 adım, ort.
  10 s** — arama → describe → SQL → `chart` → cevap. İlk sürüm 0/3: `answer_must_contain`
  "grafik" arıyordu, model "çizgi grafiği hazır" yazdı; Türkçe ek k→ğ yumuşattı. İğne "grafi".
- Seed regresyonu G1–G7: bkz. commit mesajı.

## Açık kalan
- 81 il haritasının gerçek sınır dosyası ve demo veritabanına 81 FinTürk serisinin çekilmesi
  (kaynak: BDDK FinTürk, canlı). İkisi de operatör işi; araç hazır.
- `workspace_compute_column` türetilmiş kolona birim atayamıyor; yüzde değişim grafiği
  "birim belirtilmemiş" diye çıkıyor. Doğru ama kaba; `unit` parametresi C2 ile birlikte.
- Grafik belirtimi kanıt panelinde (C2) satırdan RAW'a inen zincire bağlanacak: her nokta
  `source_observation_dates` ve `artifact_sha256_list` taşıyor, tooltip'e girmedi.

## İlgili
ADR-0010 (modele seçenek bırakma), ADR-0027 (anlatı doğrulama: sayı için ne ise denetçi
grafik için o), ADR-0029 (sınır doğrulayıcı: referans ve politika katmanları), ADR-0031
(Gold kolon adları).
