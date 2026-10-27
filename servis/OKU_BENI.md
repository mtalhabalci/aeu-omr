# Nota okuma servisi

Musiki Akademisi uygulamasının çağırdığı servis: fotoğraf ya da PDF alır, MusicXML döndürür. Model v24'tür (tezin
son modeli v20'nin karışımı + 1.600 hakemli el yazısı porte; çözümleme kuralları açık). Tez v20'de kalır. Uygulamada ve servis yanıtlarında kaynak aldığımız açık kaynak
projenin adı geçmez (Talha'nın kuralı); MusicXML'deki `<software>` alanı `OMR_YAZILIM` ile verilir.

## Çalıştırma

    cd C:\projects\yl\homr
    C:\projects\yl\venv\Scripts\python.exe -m servis.nota_servisi

`127.0.0.1:8765` adresinde dinler. Model ilk açılışta yüklenir (~10 sn).

| Ortam değişkeni | Varsayılan | Ne işe yarar |
|---|---|---|
| `OMR_MODEL` | `training/architecture/transformer/pytorch_model_1-819bee2…pth` (v24) | ağırlık dosyası (git dışında) |
| `OMR_MODEL_SURUM` | `v24+kurallar-2026-10-16` | yanıttaki `modelVersion` |
| `OMR_YAZILIM` | `Musiki Akademisi OMR` | MusicXML `<software>` |
| `OMR_ANAHTAR` | boş | doluysa `X-Omr-Anahtar` başlığı buna eşit olmalı |
| `OMR_PORT` | `8765` | port |
| `OMR_GPU_SEGMENTASYON` | kapalı | `1`: porte bulma da ekran kartında |
| `OMR_TEMPO_MODEL` | `training/architecture/tempo/tempo_okuyucu_1.pt\|_2.pt\|_3.pt` | tempo okuyucuların ağırlıkları (git dışında), `\|` ile ayrılmış; birden çoksa oylar, çoğunluğun okuduğu geçer; hiçbiri yoksa tempo okunmaz |
| `OMR_TEMPO_ARALIK_MODEL` | `training/architecture/tempo/tempo_okuyucu_aralik.pt` | aralıkları (♩ = 72–84) daha iyi okuyan ikinci okuyucu; yalnız aralık okuduğu yerde kullanılır, yoksa atlanır |
| `OMR_TEMEL_MODEL` | `training/architecture/transformer/pytorch_model_331-e103465…pth` | çok sesli porteleri okuyan temel model (v24'ün ince ayara başladığı homr koşusu 331; git dışında). Dosya yoksa servis yine açılır, bütün porteleri v24 okur |
| `OMR_COKSES_B` | kapalı | `1`: akor ve ikinci ses yazılır, tek porteli sistemler de iki modelle okunur (aşağıda "Çok seslilik") |

## Uç noktalar

- `POST /v1/omr` — multipart `dosya` (JPEG, PNG, WebP, PDF; en çok 20 MB), isteğe bağlı `tur` (`basili` |
  `el_yazisi`; tek model ikisini de okur, yalnız geri yazılır) ve `sayfalar` (yalnız PDF: 1 tabanlı aralık listesi,
  ör. `"1-3,5"`; boşsa bütün sayfalar; resimde yok sayılır). Yalnız seçilen sayfalar okunur; MusicXML yalnız onları
  içerir ve ölçüler yine 1'den boşluksuz numaralanır. Yanıt: `musicxml`, `modelVersion`, `olcuGuven`
  (`[{olcu, guven}]`, ölçü numaraları MusicXML'dekiyle aynı), `uyarilar`, `porteSayisi`, `sayfaSayisi` (okunan),
  `toplamSayfa`, `sayfalar` (okunan sayfa numaraları), `sureMs`, `yanitSurumu` (yanıt biçiminin sürümü, şimdi 2)
  ve `cokSesli` (okunan sistemlerden birinde birden çok porte varsa `true`: akolad, köşeli parantez ya da ortak
  ölçü çizgisiyle bağlı porteler; uygulama tam gösteremeyeceği bir notayı buradan anlar). `porteler`: okunan her porte için
  `{porte, sayfa, kutu: [x0, y0, x1, y1], olcuBas, olcuSon, sistem, parti, partiPortesi, okuyan, aeuDenetlenmeli}`
  (son beşi yanıt sürümü 2 ile geldi; "Çok seslilik"e bakın). `porte` bütün sayfalar boyunca artan sıra numarasıdır,
  çok porteli sistemde de her porte kendi numarasını alır. Kutu, porte çizgilerinin o sayfanın resmindeki
  piksel konumudur: fotoğrafta yüklenen resmin kendisi, PDF'te servisin 1920 piksel genişlikte çizdiği sayfa.
  Ölçü numaraları MusicXML'dekiyle aynıdır; satır sonunda bölünen bir ölçü iki portede de görünür, ölçüsü
  olmayan bir portede ikisi de `null`'dır. `sayfaResimleri`: okunan her sayfa için `{sayfa, genislik, yukseklik,
  dpi, kaynak}` (fotoğrafta `dpi` `null`). Kullanıcı düzeltmelerinin porte görüntüsüne eşlenmesi içindir.
  `kaynak`: `fotograf` (resim yüklendi), `tarama` (PDF sayfası bir resim: taranmış ya da fotokopi) ya da `dijital`
  (PDF sayfası nota programından çıkmış çizim). Tarama ve fotoğrafta okuma, özellikle tempo, daha az güvenilirdir.
  `tempolar`: sayfada yazılı tempo işaretleri (♪ = 112 gibi), her biri `{olcu, birim, noktali, deger, aralik,
  guven, porte, sayfa, kutu}` (kutu: işaretin sayfa resmindeki yeri); `birim` MusicXML adıyla (`eighth`,
  `quarter`, …). Aralık yazılmışsa (♩ = 72–84) `aralik` `[72, 84]`, `deger` ortası (78); değilse `aralik` `null`.
  Dörtlük karşılığı dakikada 20–300 dışında kalan okuma yanlış sayılır ve gönderilmez. Aynı işaret MusicXML'de o
  ölçünün başında `<metronome>` (aralıkta `<per-minute>72-84</per-minute>`) ve dörtlük cinsinden `<sound tempo>`
  olarak yazılır. İşaret okunamadıysa liste boştur; uygulama usule göre varsayılan tempoyu kullanır. `?kuyruk=1` ile iş kuyruğa alınır ve hemen
  `{"isId", "sayfaSayisi", "toplamSayfa"}` döner (202). İşler yalnız bellekte durur; servis yeniden başlarsa iş
  kaybolur (`GET` 404 döner, uygulama yeniden gönderir).
- `GET /v1/omr/{isId}` — `{"durum": "isleniyor" | "tamam" | "hata" | "iptal", "islenenSayfa", "islenenPorte", ...}`;
  ilerleme her sayfa bitince güncellenir.
- `DELETE /v1/omr/{isId}` — süren iş bir sonraki porteden önce durur ve `durum: "iptal"` olarak kalır (202,
  `{"isId", "durum": "iptal ediliyor"}`); bitmiş, hatalı ya da iptal edilmiş iş silinir (200, `"silindi"`); yoksa 404.
- `POST /v1/sayfa-sayisi` — multipart `dosya` → `{"sayfaSayisi"}` (resim 1).
- `GET /v1/saglik` — `{"modelVersion", "cihaz"}`
- Hatalar: `{"hata", "mesaj"}`; 400 `gecersiz_tur` / `bos_dosya` / `gecersiz_sayfalar`, 401 `yetkisiz`, 413
  `dosya_cok_buyuk`, 415 `desteklenmeyen_dosya`, 422 `porte_bulunamadi`, 500 `ic_hata`.

## Ölçü güveni

Her satırın güveni, modelin seçtiği ritim, perde ve arıza olasılıklarının en küçüğüdür; ölçü işareti, ölçü
çizgisi, tekrar ve volta satırlarında yalnız işaretin kendisi sayılır. Ölçünün güveni içindeki satırların en
düşüğüdür. 0,5'in altı `uyarilar`'a yazılır. Örnek: basılı Mus2 ve dizgi sayfalarda düşük güvenli ölçü yok, el
yazısı bir sayfada 32 ölçünün 5'i. Süreleri ölçü işaretini tutmayan ölçüler de numaralarıyla `uyarilar`'a tek
satırda yazılır ("Ölçü 6, 7: süreler ölçü işaretini tutmuyor; kontrol edilmeli."; ilk ve son ölçü yalnız
uzunsa, kısa olmaları ön vuruş olabilir); aynı numaralar `sureyiTutmayanOlculer` listesinde de gelir.

## MusicXML yapısı

- Notasız ölçü yazılmaz; ölçüler 1'den boşluksuz numaralanır.
- İleri tekrar ölçünün `left` barline'ında, geri tekrar `right`'ta. Volta numaraları sırayla (1, 2); bitişi
  okunmamış birinci volta geri tekrarda, açık kalan son volta son ölçüde (`discontinue`) kapanır.
- `location="middle"` barline yazılmaz. Süsleme (çarpma) notaları `<grace/>` ile gelir.
- Arıza adları SMuFL özniteliğiyle: AEU (`accidentalKomaFlat` …) ve THM 2/3 koma (`accidental2CommaSharp`,
  `accidental3CommaSharp`, `accidental2CommaFlat`, `accidental3CommaFlat`).

## Çok seslilik (yanıt sürümü 2)

v24 makam notasında ince ayar görürken çok sesliliği unuttu: akor yazmıyor, büyük portede alt porteyi atıyor, fa ve
do anahtarını sol anahtarı sanıyor. İnce ayarın başladığı homr temel modeli (koşu 331) bunları hâlâ okuyor ama AEU
arızalarını bilmiyor. Servis ikisini birlikte kullanır (çok seslilik sınavının karma okuyucusu,
`C:\projects\yl\cokses-sinav\RAPOR.md`).

**Okuma.**
- Porte bulucu porteleri sistemlere ayırır (akolad, köşeli parantez ya da ortak ölçü çizgisi bağlar). Bir sistemin
  porteleri artık büyük porte resminde birleştirilmez; her porte tek başına kesilip okunur.
- Birden çok porteli sistemde her porteyi önce temel model okur. Okuması akor, ikinci porte ya da sol anahtarı
  dışında bir anahtar gösterirse o okuma alınır (`okuyan: "temel"`). Göstermezse porteyi v24 okur (`okuyan: "v24"`),
  AEU arızaları da doğru gelir.
- Tek porteli sistemlere (makam notasının olağan sayfası) dokunulmaz: yalnız v24 okur, sonuç önceki servisle bayt
  bayt aynıdır.
- Sayfanın çoğu tek porteliyse, ne akoladı ne köşeli parantezi olan çok porteli bir "sistem" tesadüfen değen
  porteler sayılır (uzun sap, bağ, volta çizgisi) ve porteleri tek tek okunur.

**Parçalar.** Sistemin başındaki dikey işaretler sayfa resminde ölçülür (`homr/staff_groups.py`): akolad kıvrılır,
köşeli parantez düz ve kalın bir çubuktur, uçları dış çizgileri aşar; ince düz çizgi sistemin başlangıç çizgisidir.
- Akoladlı porte çifti tek parça olur: `<staves>2</staves>`, her notada `<staff>`, parça
  `<part-group type="start|stop"><group-symbol>brace</group-symbol>` içinde.
- Köşeli parantezli grup `group-symbol` `bracket` olan bir `<part-group>` olur, her portesi ayrı parça.
- Diğer her porte kendi parçasıdır.
- Parçalar en çok porteli sistemden (onların en sık görülen düzeninden) çıkar. Aynı sayıda portesi olan sistem
  porte porte aynı parçalara gider. Daha az portesi olan sistem, anahtarı ve akoladı en iyi uyan parçalara sırayla
  yerleşir; o sistemde olmayan parça tam ölçü susu alır.
- Bir sistemin bütün parçaları o sistemin en uzun okumasının ölçü sayısını alır; kısa kalan porte tam ölçü
  susuyla tamamlanır. Böylece yanlış okunan bir ölçü çizgisi parçaları yalnız kendi sisteminde kaydırır.
- Sistemin solunda porte adı yazılıysa (Soprano, Piano, S, A …) OCR ile okunur ve `<part-name>` olur. Adın
  okunduğu ilk sistem geçer. Okunamazsa ad eskisi gibi `Voice` (tek porte) ya da `Piano` (iki porte) kalır.
- Alt portenin sesleri 5-8 numaralıdır (homr'un düzeni: porte başına 4 ses). Parçalar arası ölçü numaraları
  aynıdır.

**Akor ve ikinci ses (`OMR_COKSES_B`).**
- Kapalıyken (varsayılan) her porte tek çizgi olarak yazılır. Her vuruşta orada başlayan en tiz nota kalır, bir
  sonraki vuruşa kadar sürer ("üst ses"). Akordan en tiz perde kalır. Alttaki ses kıpırdarken tutulan üst nota orada
  kesilir ve kesilen notanın bağı düşer. Yalnız sus başlayan yerde en kısa sus kalır. `uyarilar`'a "Porte 3, 4:
  akor ya da ikinci ses vardı; yalnız üst ses yazıldı." satırı düşer.
- Açıkken (`OMR_COKSES_B=1`) temel modelin akorları ve ikinci sesleri yazılır: `<chord/>`, `<voice>`, `<backup>`.
  Temel modelin bazen ürettiği "susla başlayan akor" (geçersiz MusicXML) düzeltilir: sus akordan ayrılır,
  `<backup>` ile kendi sesi olur. Tek porteli sistemler de iki modelle okunur (tek portede akor için), bu yüzden
  makam sayfası da iki kat sürer. Temel model akor görmezse yine v24'ün okuması yazılır.

**Yanıt.**
- `yanitSurumu: 2`. `cokSesli`: bir sistemde birden çok porte ya da akolad/köşeli parantez varsa `true`.
- `porteler[]`'e eklenenler. Eski alanlar aynen durur; `porte` yine bütün sayfalar boyunca artan sıra numarasıdır.
  - `sistem`: 1'den başlar; aynı sistemin porteleri aynı numarayı taşır.
  - `parti`: 0'dan başlar, MusicXML'deki P1, P2, … sırası.
  - `partiPortesi`: 1'den başlar; parça içindeki porte, MusicXML'deki `<staff>` numarası.
  - `okuyan`: `"v24"` ya da `"temel"`.
  - `aeuDenetlenmeli`: temel model okuduysa `true`. Temel model AEU koma arızalarını tanımaz; bu portelerin arızaları
    düz diyez/bemol gelir, uygulama kullanıcıya göstermeli.
- Tek porteli notada `sistem` her portede bir artar, `parti` 0, `partiPortesi` 1, `okuyan` `"v24"`,
  `aeuDenetlenmeli` `false`.
- Temel modelin okuduğu portelerin numaraları `uyarilar`'da tek satırda gelir.

**Sınav (27.10.2026).** Çok seslilik sınavının 76 sistemi (`C:\projects\yl\cokses-sinav`, kitap telifli, depoya
girmez) servisin kendi yoluyla okundu, `olc.py` ile uzlaşılmış etiketlere göre puanlandı. Nota F1:

| Okuyucu | Hepsi | Büyük porte | Tek porte akor | Ezgi | Çok porte | Akor tam |
|---|---|---|---|---|---|---|
| Önceki servis | 0,42 | 0,32 | 0,47 | 0,94 | 0,30 | 0,32 |
| Sınavın karma okuyucusu (hazır porte kesitleri) | 0,90 | 0,90 | 0,95 | 0,95 | 0,87 | 0,88 |
| Servis, `OMR_COKSES_B` kapalı | 0,71 | 0,64 | 0,47 | 0,94 | 0,83 | 0,53 |
| Servis, `OMR_COKSES_B=1` | 0,88 | 0,85 | 0,94 | 0,94 | 0,90 | 0,85 |
| Servis kapalı, resme 60 px beyaz kenar | 0,74 | 0,68 | 0,51 | 0,94 | 0,84 | 0,56 |
| Servis `=1`, resme 60 px beyaz kenar | 0,905 | 0,896 | 0,951 | 0,944 | 0,899 | 0,89 |

- 50 çok porteli sistemin hepsinde parça yapısı doğru çıktı: 34 akoladlı çift, 12 köşeli parantez ya da bağsız
  porte, 4 ses + piyano.
- Kapalıyken alt porte artık var, perdesi doğru: büyük portede yazılan notaların %84'ü doğru (önceki servis %58),
  ama akorların alt sesleri yazılmadığı için bulunan %51. Fa ve do anahtarlı portelerde F1 0 → 0,64 (kenarlı 0,69).
- Sınav resimleri mürekkebin bittiği yerden kesilmiş. homr'un porte kesimi resmin kenarına değen büyük şekilleri
  siler; alt portenin aşağı saplı kirişleri böyle gidiyor. Beyaz kenar eklenince sonuç karma okuyucuya eşit. Gerçek
  sayfada porte ile kâğıt kenarı arasında boşluk olur; sıkı kırpılmış fotoğrafta aynı kayıp olabilir.
- Çıkan 152 MusicXML'in hepsi MusicXML 4.0 şemasına (XSD) uyuyor. `=1` çıktılarında 700 akor notası var; hiçbiri
  susla başlamıyor.
- Tek porteli 30 makam sayfasında (neyzen.com'dan 20, SymbTr Mus2'den 10) MusicXML önceki servisle bayt bayt aynı;
  yanıt da yeni alanlar dışında aynı. `OMR_COKSES_B=1` iken 27'si aynı: 3 sayfada 255 portenin 9'unda temel model
  akor gördü (sayfa başına 1-3 akor). Bu porteler temel modelden gelir ve AEU arızalarını kaybeder
  (`aeuDenetlenmeli`). 30 sayfanın süresi 967 sn'den 1.323 sn'ye çıktı.

**Süre ve bellek (27.10.2026, bu bilgisayar, yalnız işlemci, ekran kartı gizli).** Süre sayfa başına.

| | Önceki servis | `OMR_COKSES_B` kapalı | `OMR_COKSES_B=1` |
|---|---:|---:|---:|
| Açılıştan sonra bellek | 1.208 MB | 1.576 MB | 1.577 MB |
| Tek porteli sayfa (neyzen hicaz hümayun, 11 porte) | 35,4 sn | 35,4 sn | 55,5 sn |
| Piyano sayfası (Cemal Reşit Rey, 4 sistem, 8 porte) | 20,9 sn (alt porteler yok) | 52,4 sn | 55,1 sn |
| Piyano sayfası (s081, 5 sistem, 10 porte) | 13,8 sn (alt porteler yok) | 29,8 sn | 31,3 sn |
| Tepe bellek (üç sayfa) | 1.992 MB | 2.468 MB | 2.465 MB |

- İkinci model belleğe ~370 MB ekler, tepe bellekte ~480 MB.
- Tek porteli sayfa kapalıyken eskisi kadar sürer; `=1` iken her porteyi iki model okur, ~%55 uzar.
- Çok porteli sayfada her porte ayrı okunur (önceki servis iki porteyi tek resimde okuyordu). Temel model akor
  görürse v24 hiç çalışmaz; görmezse iki model de okur. Porte başına 3-6,5 sn.

**Sınırlar.**
- Temel modelin okuduğu portede AEU arızası düz diyez/bemol olur (`aeuDenetlenmeli`). Çok sesli AEU notası için
  kalıcı çözüm iki sesliliği de bilen yeni bir model (v25).
- Tenor anahtarı (sol-8) modellerin sözlüğünde yok; 8'i sayfadan ayrıca okunur (aşağıda "Oktav anahtarı").
- İç köşeli parantez (bir grubun içindeki ikinci parantez, keman I-II gibi) yazılmaz; yalnız dıştaki.
- Ses numaraları sap yönüne göre değil zamandaki çakışmaya göre verilir (sınavda ses ayrımı katı ölçümle %70).
- Tek porteyi saran köşeli parantez aranmaz; tek porteli sistem hep tek parçadır.

## Oktav anahtarı (tenor anahtarı)

Modellerin sözlüğünde 8'li sol anahtarı yok. Tenor portesi (altında küçük 8 olan sol anahtarı) `clef_G2` okunur ve
bütün sesler bir oktav tiz çıkar. Servis, okuması sol anahtarıyla başlayan her portede 8'i sayfa resminde arar
(`homr/octave_clef.py`):

1. **Anahtar.** Portenin başında porte çizgileri silinir (çizgi üstündeki kısa dikey mürekkep). Porte başına en yakın,
   üst çizgiyi aşan, alt çizgiye inen, orta çizgilerde de geniş olan uzun parça anahtardır. Köşeli parantezin ve
   akoladın çubuğu orada dardır.
2. **Rakam.** Anahtarın altındaki bantta (8va için üstündekinde), tek mürekkep parçasında üst üste iki delik aranır.
   Boyu rakam kadar olmalı, anahtarın ortasının altında ve ucuna yakın durmalı, iki yanı boş olmalı. Ölçü numarası,
   söz hecesi ve "O" (tek delik) böyle elenir. Anahtarın topuna değen 8 de bulunur. Bulanık ya da kaba baskıda 8'in
   bir deliği dolabilir; o zaman tek delik 8'in üst ya da alt gözü sayılır.
3. **OCR.** Başlık bilgisini okuyan RapidOCR'ın tanıyıcısı rakamın kutusunu okur. "8" okumazsa (güven iki delikte
   0,5'ten, tek delikte 0,55'ten azsa) anahtar düz sol sayılır.

Bulununca MusicXML'de anahtar `<clef><sign>G</sign><line>2</line><clef-octave-change>-1</clef-octave-change></clef>`
olur (8 üstteyse `1`), portenin notaları bir oktav pes (tiz) yazılır. `uyarilar`'a "Porte 3: sol anahtarının altında
8 var (tenor anahtarı); notalar porte üzerinde göründüklerinden bir oktav pes yazıldı. …" satırı düşer. 8 bulunmayan
sayfanın çıktısı değişmez.

Sistemin üst portesinin üstünde 8 aranmaz. Orada sistemin ilk ölçüsünün numarası durur, tam anahtarın üstünde
(sınavın porte kesitlerinde bir "4" ile bir "6" orada). 8. ölçüyle başlayan bir sistem 8va anahtarı sanılırdı.

**Ölçüm (27.10.2026).**

| Girdi | Tenor portesi (8'li) | Bulunan | Yanlış bulunan (8'siz portelerde) |
|---|---:|---:|---:|
| Sınavın 76 sistemi, servisin porte bulucusu | 7 | 7 | 0 / 140 |
| Kitabın 752 sistem resmi, servisin porte bulucusu | 72 | 56 | 0 / 1.364 |
| Hazır porte kesitleri (1.527; 35'inde porte bulunamadı) | 69 | 57 | 0 / 1.356 |

- Doğru cevap sınavda uzlaşılmış etiketler, kitapta ve kesitlerde envanterin anahtar sütunu. Kitap taramasında 85,
  kesitlerde 67 portenin anahtarı bilinmiyor (bulunan
  porte sayısı envanterle tutmadı ya da envanterde "?"); bunlar sayılmadı, aralarında 8 bulunan da yok. Bulunan 56
  sistem portesine ve 57 kesite tek tek bakıldı: hepsinde anahtarın altında 8 var, kutu 8'in üstünde.
- Kitapta kaçan 16 tenor: 7'si üç sayfanın (p193, p200, p201) pikselli taraması, 8 birkaç pikselden ibaret. 2'sinde
  8 ince, OCR "X" okuyor. 4'ünde OCR başka harf ya da düşük güvenle "8" okuyor. 2'sinde 8 topa kaynamış, aday
  çıkmıyor. 1'i kalın çizgili bir tarama, anahtar bulunamıyor.
- İki işaret birlikte gerekli. Tek başına şekil (iki delik) kitapta 54 aday verdi, hepsi 8. Tek delikli 16 adayın
  8'i 8, ötekiler "4", "6", "9", "A" (sistemlerin üst portesinin üstündekiler dahil; OCR hepsini eledi). Şekilsiz OCR, anahtarın altında sabit bir bantta sınavın
  7 tenorundan 5'ini okudu: iki taramada bant anahtarın topunu da aldı, "B" ve "g" okundu.
- Parti adları ("T", "Tenor") kullanılmıyor; sınavın 7 tenoru adsız da bulundu.
- Puan. Sınavın `olc.py`'si tenor portesini, iki anahtarın oktav farkı kadar kaydırarak karşılaştırır. Bu yüzden
  nota F1'i değişmedi (`OMR_COKSES_B` kapalı 0,713, açık 0,877); kaydırmak zorunda kaldığı porte 7'den 0'a indi.
  Sesler kaydırmadan, yazıldığı gibi karşılaştırılınca nota F1 kapalıyken 0,679 → 0,713, açıkken 0,845 → 0,877.
  Tenor portelerinin nota F1'i 0'dan 0,69–1,00'a çıktı (p226'nın tenoru bu sistemde yalnız sus).
- Sınavın 69 sistemi önceki çıktıyla bayt bayt aynı (kapalı ve açık). Değişen yalnız 7 tenor sistemi: anahtara
  `<clef-octave-change>-1</clef-octave-change>` eklendi, tenor notalarının `<octave>`'ı bir azaldı.
- Tek porteli 30 makam sayfası (neyzen.com'dan 20, SymbTr Mus2'den 10, önceki değişikliğin bayt sınavı): MusicXML
  ve yanıt `OMR_COKSES_B` kapalıyken de açıkken de önceki servisle bayt bayt aynı (30/30). Hiçbir portede 8
  bulunmadı.
- Süre: 8'siz portede arama ortalama 1,5 ms (en çok 17 ms); OCR yalnız aday bulununca çalışır, 8'li portede 8 ms.
  Bellek değişmez (OCR başlık bilgisi için zaten yüklü).

**Sınırlar.**
- Kötü taramada 8 kaçabilir; o porte eskisi gibi bir oktav tiz yazılır.
- 8 her portede ayrı aranır. Bir sistemde bulunup ötekinde kaçarsa parça sistemden sisteme bir oktav atlar.
- Sistemin üst portesinde 8va aranmaz. 15'li anahtar ve 8'li fa anahtarı hiç aranmaz.

## Süre (14.10.2026, bu bilgisayar)

| Sayfa | Porte | Ekran kartı | İşlemci |
|---|---:|---:|---:|
| Mus2, 2 sayfa (hicaz) | 16 | 13,6 sn | – |
| Dizgi, 1 sayfa | 8 | 6,6–7,0 sn | 11,2 sn |
| El yazısı, 1 sayfa | 8 | 7,0 sn | – |

## Örnekler

`servis/ornekler/`: aynı servisin okuduğu üç sayfa (Mus2 basılı hicaz, Erdinç Bal dizgi, Erdinç Bal el yazısı;
hiçbiri eğitimde yok), MusicXML ve yanıtın geri kalanı (`.json`). `python -m servis.ornek_uret` yeniden üretir.
