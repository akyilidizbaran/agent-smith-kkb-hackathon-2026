# ADR-0068 — İşlem kapsamlı ve güncel mesaja bağlı yazma onayı

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** bağımsız kontrol R03 → düzeltme D03 (M04-T07/T09, A21b) ·
**Değiştirdiği:** ADR-0039 terfi kapısının onay kaynağı

## Bağlam

`promote_draft` onayı birikmiş bütün sohbet metninde arıyordu. Önceki turda "sicaklik taslağını onaylıyorum" yazılmışsa
güncel "Şimdi sicaklik yayınlama." mesajı bile terfiye yetiyordu. Ayrıca Gold'un hesap rızası ("onaylıyorum", "kabul
ediyorum") ile kalıcı yayın onayı aynı sözcükleri paylaşıyordu.

## Karar

- Kayıt defteri bu turun mesajını (`current_message`) ve tur sayacını geçmişten ayrı tutar. Yazma onayı yalnız güncel
  mesaja bakar; niyet kapısının adres kontrolü geçmişe bakmaya devam eder (kullanıcının önceki turda verdiği adres meşrudur).
- **Bekleyen işlem** (`core/approvals.py`): hedef seri, işlem türü, gösterilen kapsam özeti, gösterildiği tur. Taslak
  eklenince ve onaysız terfi denemesi reddedilince kaydedilir.
- **Karar tablosu:** güncel ret/iptal her zaman kazanır ve bekleyeni kapatır; onay + hedef seri → yalnız o işlem; onay başka
  seri adlandırıyorsa ret/netleştirme; kısa "evet" yalnız önceki turda gösterilmiş tek bekleyen işlem varsa geçer, birden
  çoksa sorulur; güncel mesajda onay yoksa eski onay yetki sayılmaz.
- **Tüketim:** onay denemede tüketilir. Başarısız CLI yeniden onay ister; başarılı terfiden sonra seri taslak olmadığı için
  tekrar çağrı ikinci işlem üretmez.
- **Sınırlar:** dış içerik kullanıcı mesajı değildir; oturum sıfırlama ve profil değişimi ajanı ve kayıt defterini yeniden
  kurduğu için bekleyen işlemler düşer; Analyst kayıt defterinde araç yoktur.
- **Rıza ayrımı:** Gold hesabı için "doğrulanmamış olsa da kullan / yine de kullan / riski kabul"; kalıcı yayın için
  "onaylıyorum / kataloğa al / yayınla". Biri diğerini karşılamaz.

## Sonuç

`tests/test_d03_onay.py` gerçek `ToolRegistry` yolunda (CLI çağrıları sayılarak): eski onay + güncel ret, A onayı + B
hedefi, açık hedef ve tekrar çağrı, kısa evet tek/çok bekleyen, yeni kayıt defteri, başarısız işlem yeniden onay, dış içerik
ve Analyst. Mevcut terfi testleri güncel mesaj alanına taşındı.
