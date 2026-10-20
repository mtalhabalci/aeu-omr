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
resimler bozmasızdır. Sonuçlar tezin son modeline (v20) aittir.

| Ölçü | AEU-OMR |
|---|---|
| Sembol doğruluğu | %99,8 |
| Arıza işaretinin doğru sınıfı (4.723 işaret) | %99,8 |
| Donanım satırı (2.728) | 2.728 |
| Usûl (154) | 154 |
| Hatasız porte (1.303) | 1.249 (%95,9) |

AEU-OMR, AEU'nun 1, 4 ve 5 komalık arıza sınıflarının her birini %99,6'nın üstünde bulmuştur. Okuma serbesttir;
yalnız donanım satırı öğretmen destekli okumayla sayılmıştır.

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

## Lisans

[AGPL-3.0](LICENSE). Lisans homr'dan devralınmıştır.

## Teşekkür

[homr](https://github.com/liebharc/homr), [oemer](https://github.com/BreezeWhite/oemer) ve
[Polyphonic-TrOMR](https://github.com/NetEase/Polyphonic-TrOMR) projelerine teşekkür ederim.
