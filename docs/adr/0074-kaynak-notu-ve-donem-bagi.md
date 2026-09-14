# ADR-0074 — Alternatif kaynak cevapta adlandırılır; sayı yanında yazılan döneme bağlanır

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** düzeltme planı K02-T07 (A18), K02-T14 (M13-T04/T07)

## Bağlam

- **A18:** erişim politikası kaynak sabit değilken "alternatif dene, değişikliği söyle" diyordu. Ama erişim hataları tekrar
  denenemez olduğu için döngü ilk hatada araçsız son tura geçiyor, model aynı turda başka kaynak deneyemiyordu. Denerse de
  cevabın kaynağı adlandırdığını denetleyen bir kapı yoktu.
- **M13-T04/T07:** kanıt paneli cevaptaki sayıyı tabloda herhangi bir satırda bulunca doğrulanmış sayıyordu; "Aralık 2025'te
  100" yazılıp 100 Aralık 2024 satırında olsa da eşleşiyordu. Önceki tablo eşleşmesi "önceki tablo (-1)" diye, kaynaksız
  gösteriliyordu.

## Karar

- **Tur sonu bayrağı:** `ToolError.terminal` (None = eski davranış). Erişim hatası zarfı kaynak sabitse `True` (kullanıcıya
  sorulur), serbestse `False`: aynı adres tekrar denenmez (tekrar kilidi), ama model başka kaynağı deneyebilir.
- **Kaynak notu:** turda erişilemeyen bir `web_url` adresinden sonra başka bir adresten veri kullanıldıysa ve cevap o
  kaynağın alan adını anmıyorsa, bütün çıkış yollarında deterministik not eklenir: "Kaynak notu: A adresine erişilemedi;
  veriler B kaynağından alındı."
- **Dönem bağı:** cevapta sayının aynı cümlesinde, ona en yakın yıl ve ay yazıyorsa eşleşen satırların dönemi bununla
  karşılaştırılır. Uyan satır varsa o satır gösterilir; yoksa `period_warning` işaretlenir ve "sayılar" rozeti yeşil olmaz.
  Dönem yazılmamışsa bağ denetimi yapılmaz.
- **Önceki tablo sürümü:** eşleşme oturum kaynağının kimliği (kN), kolon kaynağı ve SQL'iyle gösterilir; kaynak kimliği
  olmayan anlık görüntüler bunu açıkça söyler.

## Sonuç

`tests/test_agent_loop.py::test_k02_t07_…` (a.example 404 → b.example; not eklenir, cevap adlandırıyorsa eklenmez),
`tests/test_access_policy.py` (serbest kaynakta `terminal=False`, sabitte `True`), `tests/test_k02_donem_bagi.py` (yanlış dönem,
doğru dönem, dönemsiz cümle, önceki tablo etiketi). Ajan testleri 461.
