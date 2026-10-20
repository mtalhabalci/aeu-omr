# AEU-OMR

**Arel-Ezgi-Uzdilek OMR**: basılı Türk müziği notasını MusicXML'e çeviren optik müzik tanıma (OMR) sistemi.

AEU-OMR, Batı müziği notası için geliştirilmiş açık kaynak [homr](https://github.com/liebharc/homr) sisteminin
Türk müziği notasına uyarlanmış hâlidir. homr'un porteleri okuyan modelinin mimarisi değiştirilmemiştir. Modelin
sözlüğüne Türk müziği notasının üç sembol grubu eklenmiş ve model bu sözlükle yeniden eğitilmiştir:

- Arel-Ezgi-Uzdilek (AEU) ses sisteminin 1, 4, 5 ve 8 komalık diyez ve bemolleri
- notaları koma değerleriyle yazan donanımlar
- iki rakamıyla birlikte usûl rakamları (ör. 9/8, 10/8, 28/4)

*In English:* AEU-OMR adapts the open-source OMR system homr, built for Western notation, to printed Turkish makam
notation. The architecture of homr's staff reader is unchanged. Its vocabulary gains the Arel-Ezgi-Uzdilek comma
accidentals, key signatures written sign by sign with their comma values, and two-digit usul (meter) signs. The model
is fine-tuned in full on labels generated from the SymbTr corpus and audited note by note against the printed page.

## Sonuçlar

Eğitimde görülmemiş 158 eserin 1.303 portesi üzerinde ölçülmüştür. Sınav porteleri SymbTr'nin Mus2 baskılarıdır,
resimler bozmasızdır. Tablodaki AEU-OMR sütunu tezin son modelidir (v20).

| Ölçü | homr | AEU-OMR |
|---|---|---|
| Sembol doğruluğu | %76,1 | %99,8 |
| Arıza işaretinin doğru sınıfı (4.723 işaret) | %16,2 | %99,8 |
| Donanım satırı (2.728) | 0 | 2.728 |
| Usûl (154) | 0 | 154 |
| Hatasız porte (1.303) | 0 (%0) | 1.249 (%95,9) |

AEU-OMR, AEU'nun 1, 4 ve 5 komalık arıza sınıflarının her birini %99,6'nın üstünde bulmuştur.

Ölçüm koşulları:

- **homr sütunu:** Öğretmen destekli okumadır. Puanlama hoşgörülüdür: Batı müziğindeki diyez 4 komalık diyez, bemol
  5 komalık bemol sayılmıştır.
- **AEU-OMR sütunu:** Serbest okumadır. Yalnız donanım satırı öğretmen destekli okumayla sayılmıştır.

## Depodakiler

| Yer | Ne yapar |
|---|---|
| `homr/transformer/vocabulary.py` | Genişletilmiş sözlük: koma değerli arızalar (`sharp1`…`flat8`), `keyAccidental` donanım satırı, `timeSignature_Ü/A` usûl jetonları |
| `homr/makam_key.py` | Sayfada basılı işaretten her notanın çalınan perdesini bulan ölçü kuralı |
| `training/datasets/convert_symbtr.py` | SymbTr'nin .mu2 dosyalarından ve Mus2 PDF'lerinden porte resmi ve etiket üretimi |
| `training/audit_labels.py` | Etiketlerin PDF'teki glif koordinatlarıyla sayfaya karşı nota nota denetlenmesi |
| `training/train.py` | İnce ayar (ağın tamamı) |
| `training/evaluate_makam.py` | Sınav: sembol, nota ve arıza sınıfı ölçümleri, hatasız porte oranı |
| `servis/` | HTTP servisi: fotoğraf ya da PDF alır, MusicXML döndürür (`servis/OKU_BENI.md`) |
| `servis/docker/` | Servisin işlemcide çalışan Docker imajı (`servis/docker/OKU_BENI.md`) |

homr'un kendi kurulum ve kullanım belgesi [README_homr.md](README_homr.md) dosyasındadır.

## Çalışan sürüm

Musiki Akademisi uygulamasının nota okuma servisi bu depodaki `aeu-omr` dalının kodundan çalışır. Model
`v24+kurallar-2026-10-16`'dır: tez modeli v20'nin eğitim karışımına 1.600 hakemli el yazısı porte eklenmiştir.

Bu depoda bulunmayanlar:

- **Model ağırlıkları:** git'e girmez.
- **Eğitim verisi:** SymbTr'den türetilmiştir. SymbTr CC BY-NC-SA 4.0 lisanslıdır; veri `convert_symbtr.py` ile
  [SymbTr](https://github.com/MTG/SymbTr) 2.0.0'dan yeniden üretilebilir.

## Atıf

Bu çalışma Muhammed Talha BALCI'nın Bandırma Onyedi Eylül Üniversitesi Lisansüstü Eğitim Enstitüsü Bilgisayar
Mühendisliği Anabilim Dalı'nda Doç. Dr. İlyas ÖZER danışmanlığında ve Prof. Dr. Alper AKDENİZ ikinci danışmanlığında
hazırladığı "Türk Müzik Notasyonunda Optik Müzik Okuma" başlıklı yüksek lisans tezinden üretilmiştir. Tezden
türetilen makale hazırlanmaktadır:

> Balcı, M. T., Özer, İ. ve Akdeniz, A. Batı Müziği Notası İçin Eğitilmiş Bir Optik Müzik Okuyucusunun Basılı Türk
> Müziği Notasına Uyarlanması (hazırlanıyor).

## Lisans

[AGPL-3.0](LICENSE). Lisans homr'dan devralınmıştır.

## Teşekkür

Bu çalışma homr olmadan yapılamazdı. homr'un kodu, porte bulan bölütleme ağı ve Batı müziği notasıyla eğitilmiş
ağırlıkları bu çalışmanın temelidir. Bu sistemi açık kaynak olarak paylaşan ve Türk müziği uyarlamasının
kullanılmasına izin veren homr'un yazarı [liebharc](https://github.com/liebharc)'a ve homr'a katkıda bulunan herkese
teşekkür ederiz. homr da iki açık kaynak çalışmanın üzerine kuruludur:

- **Bölütleme:** [oemer](https://github.com/BreezeWhite/oemer)
- **Transformer modeli:** [Polyphonic-TrOMR](https://github.com/NetEase/Polyphonic-TrOMR)

Bu çalışmalara ve eserlerin sembolik ve basılı hâllerini açık olarak paylaşan SymbTr derlemine (Müzik Teknolojileri
Grubu, Universitat Pompeu Fabra) de teşekkür ederiz.
