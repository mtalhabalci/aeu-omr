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
- Tenor anahtarını (sol-8) temel model 8'siz sol okur; perdeler bir oktav yukarı yazılır.
- İç köşeli parantez (bir grubun içindeki ikinci parantez, keman I-II gibi) yazılmaz; yalnız dıştaki.
- Ses numaraları sap yönüne göre değil zamandaki çakışmaya göre verilir (sınavda ses ayrımı katı ölçümle %70).
- Tek porteyi saran köşeli parantez aranmaz; tek porteli sistem hep tek parçadır.

## Süre (14.10.2026, bu bilgisayar)

| Sayfa | Porte | Ekran kartı | İşlemci |
|---|---:|---:|---:|
| Mus2, 2 sayfa (hicaz) | 16 | 13,6 sn | – |
| Dizgi, 1 sayfa | 8 | 6,6–7,0 sn | 11,2 sn |
| El yazısı, 1 sayfa | 8 | 7,0 sn | – |

## Örnekler

`servis/ornekler/`: aynı servisin okuduğu üç sayfa (Mus2 basılı hicaz, Erdinç Bal dizgi, Erdinç Bal el yazısı;
hiçbiri eğitimde yok), MusicXML ve yanıtın geri kalanı (`.json`). `python -m servis.ornek_uret` yeniden üretir.
