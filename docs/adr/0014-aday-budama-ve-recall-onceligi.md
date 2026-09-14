# ADR-0014: Aday budamada recall önceliği

**Durum:** Planlandı · **Tarih:** 2026-09-09

## Bağlam
Bağlam ön-yükleme (ADR-0013) kaçınılmaz olarak bir **budama** içerir: modele
kataloğun tamamı değil, ilgili görülen kısmı verilir. Uber QueryGPT bunun için
ayrı bir "Column Prune Agent" çalıştırıyor.

Doğal soru: **yanlış olanı budarsak ne olur?**

## Hata modu — ve neden en tehlikelisi bu
Budama hatası iki şekilde ortaya çıkar:

1. **Görünür hata:** model aradığını bulamaz, "bu veri yok" der. Rahatsız edici
   ama dürüst; kullanıcı yanlış yönlendirilmez.
2. **Sessiz hata:** model, budanmış kolonun yerine **eldeki başka bir kolonu**
   kullanır. Sorgu çalışır, tablo döner, sayı makul görünür — ve yanlıştır.

İkincisi güven katmanını doğrudan deler: provenance kaydı "doğru" görünür, çünkü
sorgu gerçekten o kolondan gelmiştir. Sadece **yanlış kolondur**. Bizim
senaryomuzda somut karşılığı var: "Tüketici Kredileri - Konut" budanırsa model
"Takipteki Konut Kredileri"ni kullanabilir — ikisi de gerçek, ikisi de konut,
biri canlı bakiye diğeri takipteki alacak.

## Karar
Budama **recall öncelikli** yapılacak. Beş koruma:

**1. Asimetrik maliyet kabul edilir.** Fazla aday bırakmanın maliyeti token;
eksik bırakmanın maliyeti yanlış cevap. Bu maliyetler eşit değildir, dolayısıyla
eşik cömert tarafa ayarlanır. Amaç en küçük bağlam değil, *yeterince küçük* bağlam.

**2. Dokunulmaz çekirdek.** Şu kolonlar hiçbir koşulda budanmaz: zaman kolonu,
`grain` kolonları, birim/para birimi kolonları, alt toplam bayrağı. Bunlar
sorunun konusundan bağımsız olarak her sorguda gerekebilir.

**3. Alt sınır.** Aday sayısı belirli bir eşiğin altındaysa (ör. 15 kolon)
hiç budama yapılmaz. Bizim mevcut tablomuz 7 kolonlu — budama zaten gereksiz.

**4. Şeffaflık.** Budama gizli yapılmaz. Modele "N aday gösterildi, M tanesi
gizlendi, tamamı için `lakehouse_describe` çağır" bilgisi verilir. Gizli budama
tehlikeli, görünür budama güvenlidir.

**5. Kaçış yolu açık kalır.** `search` / `describe` / `distinct_values` araçları
kayıtlı kalır (ADR-0013). Model budamanın yanlış olduğunu fark ederse tam şemaya
erişebilir.

## Bizim durumumuzda asıl budanacak şey kolon değil, değerler
Önemli bir ayrım: Uber'in kolon budaması yüzlerce kolonlu geniş tablolar içindi.
Bizim şemamız **dar** (7 kolon) ama **değer kümesi geniş** (63 kalem). Yani
uygulayacağımız şey column pruning değil, **value/entity pruning**.

Risk de burada daha yüksek: bir kolonu budarsan model onu şemada göremez ve
büyük ihtimalle fark eder; bir kalem değerini budarsan model o kalemin var
olduğunu **hiç bilmez** ve elindeki en yakın kalemi kullanır.

## Ölçüm planı
Budama uygulanmadan önce ve sonra golden set. Ek olarak ayrı bir recall metriği:
*doğru cevap için gereken kalem/kolon, aday listesinde korundu mu?* Bu metrik
uçtan uca doğruluktan bağımsız ölçülmeli — çünkü model yanlış aday listesiyle de
tesadüfen doğru cevap verebilir.
