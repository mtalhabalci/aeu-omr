# Düzeltme paketlerinden eğitim verisi

Musiki Akademisi'nde kullanıcı modelin okuduğu notayı düzeltir; uygulama düzeltmeyi bir "eğitim paketi" olarak
dışa aktarır (biçim `musiki-akademisi-duzeltme/1`, yazıcısı uygulamada
`apps/web/src/lib/server/omr/egitim-paketi.ts`). `paket_oku.py` bu paketlerdeki, kullanıcının baktığı porteleri
AEU-OMR eğitim örneğine çevirir: porte resmi (`.png`) + jeton satırları (`.tokens`), öteki eğitim setleriyle aynı
düzende.

## Çalıştırma

    cd C:\projects\yl\homr
    C:\projects\yl\venv\Scripts\python.exe -m training.duzeltme.paket_oku PAKET [PAKET ...] --cikti datasets\duzeltme

`PAKET`: uygulamanın verdiği zip (tek düzeltme ya da `index.json`'lu toplu paket) ya da açılmış klasörü.
Seçenekler: `--ad train` (alt klasör ve dizin adı), `--olcu-maskele`, `--yalniz-not`, `--onay-yeter` (aşağıda).
Model çalıştırmaz; GPU gerekmez.

Çıktı (`--cikti` klasörü):
- `<ad>/<klasör>__porteNNN.png` ve `.tokens`: kabul edilen her porte;
- `index_<ad>.txt`: `png,tokens` satırları (depo köküne göre yol, `/` ile), ayrıca `index_<ad>_basili.txt` ve
  `index_<ad>_el_yazisi.txt` (manifest'teki `tur`'a göre; eğitim el yazısını klasör adından tanır,
  `data_loader.py HANDWRITTEN_SETS`);
- `rapor.json`: paket paket, porte porte ne alındı, ne alınmadı ve neden, hangi ölçüler maskelendi, gidiş-dönüş
  sonucu. Porte başına: `olcular` ve `durumlar` servisin ölçü numaralarıyla, `maskelenenOlcular` düzeltilmiş
  notanın numaralarıyla, `nedenler` (`{neden, ayrinti}`), `gidisDonus` (`tamam` ya da fark), `uyarilar`, `ornek`
  (yazılan dosyanın adı). Paket başına ayrıca `anonimYukleme` ve `yaziciVarsayilanlari`: uygulamanın yazıcısının
  kendiliğinden koyduğu, etikete sayfanınki diye alınmayan şeyler (aşağıda "Etiket nasıl yazılır").
  `ozet.nedenler` neden kodlarının sayısıdır.

Biçimi tanınmayan paket (`bicim` başka bir şeyse, ör. `/2`) okunmaz: ileti ekrana ve `reddedilenPaketler`'e
yazılır, öteki paketler yine okunur, çıkış kodu 2 olur.

## Hangi porteler alınır

Bir porte, servisin `porteler.json`'daki bir kutusudur (çok partili notada her sistemin her portesi ayrı numara
alır). Portedeki ölçüler kutunun `olcuBas..olcuSon` aralığıdır; her ölçünün durumu `olcular.json`'dan.

1. **Bütün ölçüleri bakılmış olmalı**: her ölçü `duzeltildi` ya da `onaylandi`. Tek bir `bakilmadi` ölçü
   bütün porteyi dışarıda bırakır (`bakilmadi`). Gerekçe: bakılmamış ölçü modelin kendi okumasıdır; doğru
   sayılırsa model kendi hatasını öğrenir.
2. **Temel modelin okuduğu porte** (`aeuDenetlenmeli: true`): AEU koma arızalarını tanımaz, düz diyez/bemol
   yazmış olabilir. Bütün ölçüleri bakılmadıkça alınmaz, `--olcu-maskele` ile de (`aeu-denetlenmedi`).
   **Çok partili pakette yapısal düzeltme denetim sayılmaz** (`yalniz-yapisal`): tekrar, donanım, ölçü işareti,
   ölçü çizgisi gibi işlemleri uygulama her sürümde tasarım gereği bütün partilere uygular (parti seçici seçili
   partiye yalnız notaya dokunan işlemleri gönderir). Yalnız yapısal türlerle `duzeltildi` olmuş bir ölçü, o
   portenin notalarına bakıldığını göstermez. Notaya dokunan türler denetim sayılır (`turler`'inde `perde`,
   `ariza`, `sure`, `nota-fazla`, `nota-eksik`, `bag` ya da `susleme`).
   **Sürümünü yazmayan uygulamanın çok partili paketinde onay da sayılmaz** (`onay-butun-partilere`): manifest'te
   `uygulamaSurumu` yoksa ya da null ise (o alandan önceki bütün sürümler, 413e4b9 dahil, ve yayından önce açılmış
   sekmeden yapılan kayıtlar) uygulama bir ölçünün onayını ölçünün bütün portelerine, bütün partilere geçirmiştir.
   `uygulamaSurumu` yazan uygulamada onay yalnız kullanıcının seçtiği partiye geçer ve temel modelin okuduğu
   portenin her ölçüsü bakılmadan düzeltme bitirilemez: orada onay o portenin denetimidir. Tek partili pakette onay
   da yapısal düzeltme de yalnız o partinindir. `--onay-yeter` eski çok partili paketlerde de onayı denetim sayar
   (yapısal kuralı değiştirmez). Raporda paket başına `uygulamaSurumu`, `onayButunPartilere`,
   `yapisalDenetimSayilmaz`.
   (Bu kurallar, Talha'nın kararı beklenirken konan `aeu-yalniz-onay`'ın yerini aldı: temel modelin okuduğu porte
   yalnız onayla alınmıyordu.)
3. **Üst sese indirilmiş porte** (`ustSesKirpildi: true`): servis portedeki akoru ya da ikinci sesi kırpıp yalnız
   üst sesi yazmış (`OMR_COKSES_B=0`); düzeltme sayfadaki bütün sesleri taşıyamaz, porte alınmaz
   (`ust-ses-kirpildi`). Alanı olmayan eski yanıtlarda temel modelin okuduğu porteye yalnız uyarı yazılır.
4. **`porte: null` kayıtlar** (servis porte bilgisi yazmamış) atlanır; sayısı raporda `portesizKayit`.
5. **Gidiş-dönüş tutmalı** (aşağıda): tutmayan porte `gidis-donus` ile atlanır.
6. Ayrıca: portenin resmi (`orijinal.*`) pakette olmalı ve sayfa boyutu servisin okuduğuyla aynı olmalı
   (`resim-yok`), servis kutusu olmalı (`kutu-yok`), ölçüler portelere açıkça dağılmalı (`olcu-belirsiz`:
   porte sınırına eklenen ölçü, iki portede görünen ölçü; `bolunmus-olcu`: satır sonunda bölünen ölçünün kesimi
   okumadan bulunamadı), boş ölçü olmamalı (`bos-olcu`), düzeltme ya da okuma akor/ikinci ses taşımamalı
   (`akor-ikinci-ses`: uygulama yalnız ilk sesi tutar).
   **Eklenen ölçüler** (`eklenenOlcular`): çok partili pakette her partinin kendi kaydı vardır (`porte`, `parti`,
   `partiPortesi`); her parti yalnız kendininkini alır. Uygulama `porte`'yi kuralla verir (eklenen ölçüden önceki
   model ölçüsünün portesi, yoksa sonrakinin): porte ortasına eklenen ölçü o portededir, ama bir portenin son
   ölçüsünden sonra eklenen ölçü sayfada bir sonraki satırın başında da olabilir; bu yüzden sınırdaki eklemede
   iki porte de `olcu-belirsiz` ile atlanır (`porte` olsun olmasın). `porte` önceki ölçünün portesiyle tutmazsa da
   `olcu-belirsiz`.
7. **Aynı yüklemenin birden çok düzeltmesi** verildiyse (sonraki dışa aktarım, kullanıcının sonradan kaydettiği
   sürümü yeni bir `anonimKimlik` ile getirir) yalnız en yenisi alınır; ötekiler `yinelenen`. Yükleme manifest'teki
   `anonimYukleme`'den bilinir (yükleme kimliğinin HMAC'i, bir yüklemenin bütün sürümlerinde aynı; en yeni: en büyük
   `surum`). Alan yoksa (eski paket) orijinal dosyanın SHA-256'sına bakılır: o dosya tek bir `anonimYukleme`'de
   varsa o yüklemeye katılır, yoksa aynı dosyanın düzeltmelerinden en yenisi (`tarih`, sonra `surum`) alınır.
   Aynı dosyayı iki ayrı yükleme (iki kullanıcı) getirdiyse ikisi de alınır.

**`--olcu-maskele`**: bakılmamış ölçüleri olan porte de alınır; o ölçülerin bütün alanları `?` ile yazılır
(`?note_8 ?D5 ?_ ?_ upper`, `?barline . . . .`). Atkoşar kısmi etiketlerindeki maske budur
(`training_vocabulary.py UNVERIFIED`): satır kod çözücüye verilir, kayıp bakmaz. Hiç bakılmamış porte yine alınmaz
(`hic-bakilmamis`). Varsayılan kapalıdır, çünkü maskeli bölge Atkoşar'da modelin en zayıf kaldığı yer oldu (hiç
düzeltilmedi); bütün porte kuralı daha az ama temiz veri verir.

**`--yalniz-not`**: `duzeltildi` ölçü yalnız `turler`'i nota düzeyinde bir düzeltme içeriyorsa (`perde`, `ariza`,
`sure`, `nota-fazla`, `nota-eksik`, `bag`, `susleme`) bakılmış sayılır. Yapısal düzeltmeler (`isaret`, `donanim`,
`olcu-isareti`, `olcu-cizgisi`) bütün partilere birden uygulanır ve çok partili notada her porteyi `duzeltildi`
yapar; kullanıcı o partinin notalarına bakmamış olabilir (`yalniz-yapisal`). Tek partide yapısal düzeltmeyi
yapan zaten o porteye bakıyordur, bu yüzden varsayılan kapalı; **çok partili paketlerde açılması önerilir**.

## Etiket nasıl yazılır

Jetonlar düzeltilmiş MusicXML'den (tek partide `duzeltilmis.musicxml`, çok partide
`duzeltilmis-servis-duzeni.musicxml`, parti = `parti`, `<staff>` = `partiPortesi`) yazılır, modelin eğitildiği
biçimde: `clef_G2`, her portede `keyAccidental` satırları (koma sayılı arıza: `flat1`, `sharp4`, `flat5`…; yerleri
anahtarın standart yerleri, fa anahtarında iki basamak aşağı), ölçü işareti yalnız basıldığı portede, notada
yalnız *basılı* arıza, bağlar `tieStart/tieStop`, süsleme `note_8G`, üçleme `note_12`/`note_24`, tekrar/volta/senyo
jetonları.

Uygulamanın MusicXML'i sayfanın çizdiğini tam taşımaz: arızaları perdeden yeniden hesaplar (hatırlatma arızası
düşer), ölçü çizgisi biçimi yoktur, notanın işaretlerinden yalnız bağı ve üçleme parantezini tutar. Uygulamanın
MusicXML okuyucusu (`music-core musicxml.ts`) `<notations>` içinden yalnız `<tied>` ve `<tuplet>`'i okur;
`duzeltilmis.musicxml` uygulamanın kendi notasından yeniden yazılır (`musicxml-yaz.ts`), bu yüzden modelin okuduğu
öteki işaretlerin hepsi düzeltilmiş dosyada yoktur. Bunlar uygulamada düzenlenemez; hepsi modelin aynı sayfadaki
okumasından (`model.musicxml`) alınır ve **doğrulanmamış (`?`)** yazılır, çünkü kullanıcı bunları ekranda görüp
onaylayamaz:
- okumanın gördüğü hatırlatma arızası (`note_2 C5 ?N ?slurStop upper`);
- **notanın işaretleri**: yay (`slurStart`, `slurStop`), **fermata**, staccato, staccatissimo, tenuto, aksan
  (`accent`), nefes (`breathMark`), tril (`trill`), grupetto (`turn`), tremolo, arpej (`arpeggiate`). Okumadaki aynı
  olaydan (`<note id>`) alınır, kullanıcı perdesini ya da süresini değiştirse de (`note_2 B4 _ ?fermata_slurStop
  upper`); susun fermatası da (`rest_4 _ _ ?fermata upper`); kullanıcının susa çevirdiği notada yalnız fermata
  kalır. Birleşim sözlükte yoksa sözlükte olan en büyük alt kümesi yazılır, fermata önce. Sezura'nın jetonu yoktur
  (sözlük tutmaz), süsleme notalarının işaretleri eşlenemez;
- bağ (`tieStart`, `tieStop`) düzeltilmiş dosyadan gelir, doğrulanmış;
- kesik/çift/kalın ölçü çizgisi (`?dashedbarline`);
- portenin başında donanım basılı mı: okuma görmediyse yazılmaz.

Uygulama fermatayı (sonra belki öteki işaretleri) tutmaya başlayınca o işaret düzeltilmiş dosyadan alınır:
okuyucu bunu dosyanın kendisinden anlar. Düzeltilmiş dosyada bir türden tek bir işaret bile varsa (ör.
`<fermata/>`) o tür kullanıcınındır, doğrulanmış yazılır ve okumanınki kullanılmaz; raporda paket uyarısı
"düzeltilmiş nota şu işaretleri kendisi taşıyor". Hiç yoksa okumanınki `?` ile gelir: dosya "tutuyor ama bu
sayfada yok" ile "tutmuyor"u ayıramaz. Paket bunu biçim sürümüyle ya da bir alanla söylediğinde
(`etiket.py carried_marks` içindeki TODO) oradan alınmalı.

**Yazıcının varsayılanları** (uygulamada düzenlenemez, etiket bunları kullanıcının yazdığından ayırır; rapor
`yaziciVarsayilanlari`'nda sayar):
- **Son ölçü çizgisi**: uygulama son ölçüye hep ince-kalın çizgi koyar. Okumanın son ölçüsünde ince-kalın çizgi
  yoksa bu yazıcının varsayılanıdır; etikete okumanın çizgisi yazılır (düz `barline`, okuma kalın çift çizgi
  gördüyse `?bolddoublebarline`). Kullanıcı son ölçüleri birleştirdi ya da böldüyse de okumanın son çizgisi alınır.
- **1. ölçünün ölçü işareti**: uygulama ilk ölçüye her zaman ölçü işareti yazar. Okumanın 1. ölçüsünde `<time>`
  yoksa ve `islemler.json`'da 1. ölçüye bir `olcu-isareti` işlemi yoksa (`{"tur": "olcu-isareti", "olcu": 1,
  "once": "8/8", "sonra": "4/4"}`) bu varsayılandır, etikete yazılmaz. Böyle bir işlem varsa ölçü işareti
  kullanıcınındır ve yazılır. Eser içindeki ölçü işareti değişimi her zaman yazılır.

Notalar okumayla kimlikleriyle (`<note id>`, uygulama okumadaki kimliği korur) eşlenir; kullanıcının değiştirdiği
nota düzeltmeden gelir.

## Porte resmi

`orijinal.*` sayfası servisin okuduğu gibi hazırlanır (PDF 1920 piksel genişlikte çizilir, fotoğraf `cv2.imread`
ile; kağıda kırpma, 1920 genişlik, CLAHE) ve kutudan `prepare_staff_image`'ın kenar payları, ölçeği, kenar
temizliği ve 1280×256 tuvaliyle kesilir. Tek fark: **eğrilik düzeltmesi (dewarp) yapılmaz**, çünkü homr'un
bulduğu porte çizgileri pakette yok (yalnız kutu var). Düz tarama ve dijital PDF'te fark yok denecek kadar azdır;
eğik/kıvrık fotoğrafta resim modelin gördüğünden biraz farklı olur.

## Gidiş-dönüş denetimi

Bir partinin portelerinin jetonları servisin yaptığı gibi `newline` ile birleştirilip homr'un MusicXML yazıcısıyla
(`generate_xml`, makam çözücüsüyle) yeniden yazılır ve düzeltilmiş notayla ölçü ölçü karşılaştırılır: perde ve
çalan arıza (koma), süre, nokta, üçleme, bağ, süsleme, tekrar, volta, atlama, donanım, ölçü işareti, anahtar.
Tutmayan ölçünün portesi atlanır; raporda `gidisDonus` farkı yazar (ör. `ölçü 2: olay 2: C5+4 half yerine C5
half`).

Örnek paketlerde (`C:\projects\yl\egitim-paketi-ornek`) ve uygulamanın kendi kodu (düzenleyici,
`egitimOlculeri`, `scoreToMusicXML`) ile servis örneklerinden (`servis/ornekler`, Mus2 basma, dizgi, el yazısı)
kurulan paketlerde bütün porteler gidiş-dönüşü geçti; hiç düzeltilmemiş (yalnız onaylanmış) pakette jetonlar
okumanın jetonlarıyla aynı çıktı, yalnız uygulamanın düşürdüğü iki hatırlatma arızası `?` ile.

Gerçek servis yanıtından (v24-cokses-oktav) kurulan `ses-piyano` örneği (ses + iki porteli piyano, tek sistem,
`orijinal.png` ile) baştan sona okundu: üç porte de gidiş-dönüşü geçti; ses (porte 1) ve sol el (porte 3, ayrıca
`aeu-denetlenmedi`) bakılmamış 1. ölçü yüzünden alınmadı, sağ el (porte 2) alındı. Kesimler gözle denetlendi:
porte tuvalin ortasında, payları komşu porteye kadar; sol elin 2. ölçüsündeki donanım değişimi etikette
`keyAccidental B2 flat5` olarak ölçü çizgisinden sonra. Örnekteki sağ el düzeltmesi yapaydır (sayfadaki do, si
yapılmış): örnek eğitime girmemeli.

## Bilinen sınırlar

- `ustSesKirpildi` alanından önceki servis yanıtlarında hangi portenin üst sese indirildiği bilinmez; temel
  modelin okuduğu böyle bir porte alınırsa etiket akoru/ikinci sesi taşımayabilir (raporda uyarı).
- `1. ölçünün ölçü işareti` kuralı `islemler.json`'daki ölçü numarasına bakar (işlem anındaki numara); kullanıcı
  ölçü işaretini koyduktan sonra başa ölçü eklediyse işlem 1. ölçüde görünmez.
- Donanım işaretlerinin porte üzerindeki yeri standart kabul edilir (okumada `<key-step>` oktavsızdır).
- Okuma bir portenin başında donanım görmediyse etikete donanım yazılmaz; model gözden kaçırdıysa etiket de
  kaçırır (raporda uyarı).
- Ayıklama yalnız aynı çalıştırmaya verilen paketler arasında yapılır; daha önce yazılmış bir veri setine
  eklenmez, her çalıştırma `index_<ad>.txt`'yi baştan yazar.
