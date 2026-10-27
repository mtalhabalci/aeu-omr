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
Seçenekler: `--ad train` (alt klasör ve dizin adı), `--olcu-maskele`, `--yalniz-not` (aşağıda).
Model çalıştırmaz; GPU gerekmez.

Çıktı (`--cikti` klasörü):
- `<ad>/<klasör>__porteNNN.png` ve `.tokens`: kabul edilen her porte;
- `index_<ad>.txt`: `png,tokens` satırları (depo köküne göre yol, `/` ile), ayrıca `index_<ad>_basili.txt` ve
  `index_<ad>_el_yazisi.txt` (manifest'teki `tur`'a göre; eğitim el yazısını klasör adından tanır,
  `data_loader.py HANDWRITTEN_SETS`);
- `rapor.json`: paket paket, porte porte ne alındı, ne alınmadı ve neden, hangi ölçüler maskelendi, gidiş-dönüş
  sonucu. Porte başına: `olcular` ve `durumlar` servisin ölçü numaralarıyla, `maskelenenOlcular` düzeltilmiş
  notanın numaralarıyla, `nedenler` (`{neden, ayrinti}`), `gidisDonus` (`tamam` ya da fark), `uyarilar`, `ornek`
  (yazılan dosyanın adı). `ozet.nedenler` neden kodlarının sayısıdır.

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
3. **`porte: null` kayıtlar** (servis porte bilgisi yazmamış) atlanır; sayısı raporda `portesizKayit`.
4. **Gidiş-dönüş tutmalı** (aşağıda): tutmayan porte `gidis-donus` ile atlanır.
5. Ayrıca: portenin resmi (`orijinal.*`) pakette olmalı ve sayfa boyutu servisin okuduğuyla aynı olmalı
   (`resim-yok`), servis kutusu olmalı (`kutu-yok`), ölçüler portelere açıkça dağılmalı (`olcu-belirsiz`:
   porte sınırına eklenen ölçü, iki portede görünen ölçü; `bolunmus-olcu`: satır sonunda bölünen ölçünün kesimi
   okumadan bulunamadı), boş ölçü olmamalı (`bos-olcu`), düzeltme ya da okuma akor/ikinci ses taşımamalı
   (`akor-ikinci-ses`: uygulama yalnız ilk sesi tutar).
6. Aynı yüklenen dosyanın (manifest'teki SHA-256) birden çok düzeltmesi verildiyse (sonraki dışa aktarım,
   kullanıcının sonradan kaydettiği sürümü yeni bir `anonimKimlik` ile getirir) yalnız en yenisi (`tarih`, `surum`)
   alınır; ötekiler `yinelenen`.

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
düşer), ölçü çizgisi biçimi yoktur (son ölçüye hep ince-kalın çizgi koyar), bağ dışında yay ve artikülasyon yoktur,
ilk ölçüye sayfada olmasa da ölçü işareti yazar. Bunları modelin aynı sayfadaki okuması (`model.musicxml`) söyler
ve **doğrulanmamış (`?`)** yazılır, çünkü kullanıcı bunları ekranda görüp onaylayamaz:
- okumanın gördüğü hatırlatma arızası (`note_2 C5 ?N ?slurStop upper`), yay ve artikülasyonlar;
- kesik/çift/kalın ölçü çizgisi (`?dashedbarline`);
- portenin başında donanım ve ölçü işareti basılı mı: okuma görmediyse yazılmaz (kullanıcı ölçü işaretini
  değiştirdiyse ya da eser içinde değişiyorsa yazılır).

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

## Bilinen sınırlar

- Temel modelin okuduğu portelerde servis (çok ses kapalıyken) akoru/ikinci sesi üst sese indirir; paket bunu
  söylemez. Bu porteler alınırsa etiket o sesleri taşımaz; raporda uyarı olarak yazılır.
- Donanım işaretlerinin porte üzerindeki yeri standart kabul edilir (okumada `<key-step>` oktavsızdır).
- Okuma bir portenin başında donanım görmediyse etikete donanım yazılmaz; model gözden kaçırdıysa etiket de
  kaçırır (raporda uyarı).
- Ayıklama yalnız aynı çalıştırmaya verilen paketler arasında yapılır; daha önce yazılmış bir veri setine
  eklenmez, her çalıştırma `index_<ad>.txt`'yi baştan yazar.
