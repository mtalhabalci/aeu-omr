# Nota okuma servisi: işlemcide çalışan Docker imajı

Bu klasör, nota okuma servisinin (model v24 + çözümleme kuralları) ekran kartı olmayan bir sunucuda çalışan Docker
imajını kurmak için gereken her şeyi taşır: `Dockerfile`, sürümleri sabitlenmiş `requirements-cpu.txt` ve `kod/`
(servisin Python kodu ile model ağırlıkları). Ağırlıklar imajın içine girer; model sürümü imaj etiketiyle birlikte
değişir.

## Kurulum

    docker build -t nota-okuma:v24 .

İmaj 1,3 GB tutar (ağırlıklar 0,38 GB). İlk derleme paket indirmesiyle birkaç dakika sürer.

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
