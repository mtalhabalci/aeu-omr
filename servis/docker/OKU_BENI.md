# Nota okuma servisi: işlemcide çalışan Docker imajı

Bu klasör, nota okuma servisinin (model v24 + çözümleme kuralları, çok sesli porteler için temel model) ekran
kartı olmayan bir sunucuda çalışan Docker imajını kurmak için gereken her şeyi taşır: `Dockerfile`, sürümleri
sabitlenmiş `requirements-cpu.txt` ve `kod/` (servisin Python kodu ile model ağırlıkları). Ağırlıklar imajın içine
girer; model sürümü imaj etiketiyle birlikte değişir.

`kod/` klasörünü `python servis/docker/hazirla.py [hedef]` kurar. Ağırlıklar git'te olmadığı için çalıştığı
klasörden alınır; ağırlığı olmayan bir çalışma kopyasında (git worktree) `OMR_AGIRLIK_KOKU` ağırlıkların durduğu
klasörü gösterir (ağırlıkları taşıyan ana çalışma kopyası).

## Kurulum

    docker build -t nota-okuma:v24 .

İmajın ~1,6 GB tutması beklenir; bu sürüm henüz kurulup ölçülmedi. Ağırlıklar 0,71 GB: v24 0,30 GB, temel model
0,30 GB, geri kalanı porte bulucu, tempo ve OCR modelleri.
İlk derleme paket indirmesiyle birkaç dakika sürer.

## Çok seslilik

İmaj iki okuma modeli taşır:

- **v24** (`pytorch_model_1-819bee2…pth`): makam notası, AEU arızaları.
- **Temel model** (`pytorch_model_331-e103465…pth`): v24'ün ince ayara başladığı model. Akoru, ikinci sesi, fa ve do
  anahtarını okur.

Birden çok porteli bir sistemde her porteyi önce temel model okur. Akor, ikinci porte ya da sol anahtarı dışında bir
anahtar görürse onun okuması kalır, görmezse porteyi v24 okur. Tek porteli makam sayfası eskisi gibi yalnız v24 ile
okunur ve sonucu değişmez. Akolad tek parça (iki porte), köşeli parantez parça grubu olur. Yanıt biçimi ve sınav
sonuçları: `servis/OKU_BENI.md`, "Çok seslilik".

- `OMR_COKSES_B=0` (varsayılan): her porte tek çizgi (üst ses) olarak yazılır.
- `OMR_COKSES_B=1`: akorlar ve ikinci sesler de yazılır. Bu durumda tek porteli sayfayı da iki model okur, süre
  ~%55 uzar.
- Temel modelin dosyası yoksa servis yine açılır, bütün porteleri v24 okur.
- Bellek: ikinci model boşta ~370 MB, tepede ~480 MB ekler. Masaüstünde tepe 2,0 GB'tan 2,5 GB'a çıktı; 4 GB
  konteyner sınırı yine yeter.

## Compose

Web uygulamasıyla aynı ağda, dışarıya port açmadan:

```yaml
  nota-okuma:
    image: nota-okuma:v24        # ya da: build: /opt/nota-okuma
    restart: unless-stopped
    environment:
      OMR_ANAHTAR: ${OMR_ANAHTAR}        # isteğe bağlı; doluysa X-Omr-Anahtar başlığı buna eşit olmalı
      OMP_NUM_THREADS: "4"
      MKL_NUM_THREADS: "4"
    expose:
      - "8765"
    deploy:
      resources:
        limits:
          cpus: "4"
          memory: 4g
        reservations:
          memory: 2560m
```

Uygulama servise `http://nota-okuma:8765` adresinden bağlanır.

## Uç noktalar ve sağlık

Uç noktalar yereldeki servisle aynıdır (`POST /v1/omr`, `?kuyruk=1`, `GET /v1/omr/{isId}`, `DELETE /v1/omr/{isId}`,
`POST /v1/sayfa-sayisi`). Sağlık: `GET /v1/saglik` → `{"modelVersion": "...", "cihaz": "cpu"}`. Model açılışta
belleğe yüklenir; sağlık ucu yükleme bitince cevap verir. İmajdaki `HEALTHCHECK` açılışa 120 saniye tanır.

## Başlık bilgisi (OCR)

Yanıttaki `baslikBilgisi` (eser adı, makam, form, usul, bestekâr, güfte, yöre, kaynak) ilk sayfanın ilk portesinin
üstünden RapidOCR ile okunur. OCR modelleri (`PP-OCRv6_det_small.onnx`, `PP-OCRv6_rec_small.onnx`,
`ch_ppocr_mobile_v2.0_cls_mobile.onnx`, toplam ~32 MB) `hazirla.py` ile `ocr_modelleri/` klasörüne kopyalanır ve
imaj kurulurken RapidOCR paketinin `models` klasörüne konur; eksik olan, kurulum sırasında RapidOCR'ın kendi
adresinden indirilir (sağlama toplamıyla). Çalışan konteyner model indirmez. Başlık okuması sayfa başına ~1 sn sürer
(masaüstü işlemcide); okunamazsa `baslikBilgisi` `null` olur ve `uyarilar`a bir satır eklenir, okuma sürer.

## Ortam değişkenleri

| Değişken | Varsayılan | Not |
|---|---|---|
| `OMR_ANAHTAR` | boş | doluysa her istekte `X-Omr-Anahtar` başlığı aranır |
| `OMR_MODEL_SURUM` | `v24+kurallar-2026-10-16` | yanıttaki `modelVersion` |
| `OMR_YAZILIM` | `Musiki Akademisi OMR;AEU-OMR` | MusicXML `<software>`; `;` ile ayrılan her ad ayrı bir `<software>` satırı olur |
| `OMR_PORT` | `8765` | |
| `OMR_COKSES_B` | `0` | `1`: akor ve ikinci ses yazılır, tek porteli sistemler de iki modelle okunur |
| `OMR_TEMEL_MODEL` | `kod/training/architecture/transformer/pytorch_model_331-…pth` | temel modelin ağırlığı |
| `OMP_NUM_THREADS`, `MKL_NUM_THREADS` | `4` | modelin kullandığı iş parçacığı; `cpus` sınırıyla aynı tutun |

## Eşzamanlılık ve zaman aşımı

- Servis tek süreçle (`--workers 1`) çalışmalı: işler o sürecin belleğinde durur.
- Aynı anda tek sayfa okunur; servis bunu kendi kilidiyle sağlar. İkinci iş sırada bekler. Ayar gerekmez.
- Uygulama `?kuyruk=1` ile iş açıp durumu yoklamalı; uzun PDF'lerde eşzamanlı istek HTTP zaman aşımına takılır.
- Önerilen zaman aşımı: iş başına 60 sn + sayfa başına 60 sn (aşağıdaki ölçümün yaklaşık iki katı).
- Yeniden başlatmada sıradaki işler kaybolur. `GET` 404 döner, uygulama işi yeniden gönderir.

## Kaynak kullanımı

Okumalar HTTP üzerinden, eşzamanlı istekle yapıldı; ikisinde de 4 iş parçacığı kullanıldı.

- **Masaüstü (20.10.2026):** Bu klasördeki kodla ölçüldü. İşlemci Ryzen 5 7600X, ekran kartı gizlendi. Docker'sız
  çalıştı; tepe bellek süreç başına ölçüldü.
- **Sunucu (21.10.2026):** Keyubu VDS, sanal Ryzen 9 5950X (12 iş parçacığı). Docker imajı `nota-okuma:v24`, konteyner
  sınırı 4 CPU / 4 GB.

| İş | Masaüstü | Sunucu |
|---|---|---|
| Açılış (model yükleme) | 7–10 sn | ~11 sn |
| Boştaki bellek | - | 905 MB |
| 1 sayfa | 21–22 sn (8 porte, taranmış nihavend) | 24,6 sn (1600×1873 PNG) |
| 3 sayfa, 27 porte (dizgi peşrev) | 85–90 sn (sayfa başına ~29 sn, porte başına ~3,1 sn) | - |
| Tepe bellek | 2,1 GB | 1,58 GB |

- **Sunucuda süre:** Sanal sunucu masaüstüyle hemen hemen aynı hızda okur. Zaman aşımı önerisi bu yüzden pay bırakır.
- **Bellek:** Sayfalar sırayla okunduğundan bellek sayfa sayısıyla büyümez. 4 GB sınır yeterli pay bırakır.
- **İşlemci:** Okuma sırasında verilen 4 çekirdek dolar; boştayken işlemci kullanılmaz.
