# Nota okuma servisi: işlemcide çalışan Docker imajı

Bu klasör, nota okuma servisinin (model v24 + çözümleme kuralları) ekran kartı olmayan bir sunucuda çalışan Docker
imajını kurmak için gereken her şeyi taşır: `Dockerfile`, sürümleri sabitlenmiş `requirements-cpu.txt` ve `kod/`
(servisin Python kodu ile model ağırlıkları). Ağırlıklar imajın içine girer; model sürümü imaj etiketiyle birlikte
değişir.

## Kurulum

    docker build -t nota-okuma:v24 .

İmaj yaklaşık 2 GB tutar (PyTorch'un işlemci sürümü ~0,8 GB, ağırlıklar 0,38 GB). İlk derleme paket indirmesiyle
birkaç dakika sürer.

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

## Ortam değişkenleri

| Değişken | Varsayılan | Not |
|---|---|---|
| `OMR_ANAHTAR` | boş | doluysa her istekte `X-Omr-Anahtar` başlığı aranır |
| `OMR_MODEL_SURUM` | `v24+kurallar-2026-10-16` | yanıttaki `modelVersion` |
| `OMR_YAZILIM` | `Musiki Akademisi OMR` | MusicXML `<software>` |
| `OMR_PORT` | `8765` | |
| `OMP_NUM_THREADS`, `MKL_NUM_THREADS` | `4` | modelin kullandığı iş parçacığı; `cpus` sınırıyla aynı tutun |

## Eşzamanlılık ve zaman aşımı

- Servis tek süreçle (`--workers 1`) çalışmalı: işler o sürecin belleğinde durur.
- Aynı anda tek sayfa okunur; servis bunu kendi kilidiyle sağlar. İkinci iş sırada bekler. Ayar gerekmez.
- Uygulama `?kuyruk=1` ile iş açıp durumu yoklamalı; uzun PDF'lerde eşzamanlı istek HTTP zaman aşımına takılır.
- Önerilen zaman aşımı: iş başına 60 sn + sayfa başına 60 sn (aşağıdaki ölçümün yaklaşık iki katı).
- Yeniden başlatmada sıradaki işler kaybolur. `GET` 404 döner, uygulama işi yeniden gönderir.

## Kaynak kullanımı

20.10.2026'da bu klasördeki kodla ölçüldü. Ekran kartı gizlendi, 4 iş parçacığı kullanıldı. İşlemci Ryzen 5 7600X
(masaüstü). Okuma HTTP üzerinden, eşzamanlı istekle yapıldı.

| İş | Süre |
|---|---|
| Açılış (model yükleme) | 7–10 sn |
| 1 sayfa, 8 porte (taranmış nihavend) | 21–22 sn |
| 3 sayfa, 27 porte (dizgi peşrev) | 85–90 sn (sayfa başına ~29 sn, porte başına ~3,1 sn) |
| Tepe bellek | 2,1 GB |

- **Sunucuda süre:** Sanal sunucunun çekirdekleri masaüstü işlemciden yavaş olabilir. Süreler 1,5–2 katına çıkabilir.
- **Bellek:** Sayfalar sırayla okunduğundan bellek sayfa sayısıyla büyümez. 4 GB sınır yeterli pay bırakır.
- **İşlemci:** Okuma sırasında verilen 4 çekirdek dolar; boştayken işlemci kullanılmaz.
