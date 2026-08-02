# Knowledge Graph Production

Metin, PDF ve web kaynaklarından bilgi grafiği çıkarmak; üretilen triple'ları RAG ve çoklu model değerlendirmesiyle doğrulamak; doğrulanmış bir triple veri seti oluşturmak için geliştirilen platformdur.

## Mevcut durum

- React frontend Caddy üzerinden çalışıyor.
- FastAPI gateway, frontend API sözleşmesini sağlıyor.
- Wikontic ayrı bir servis olarak çalışıyor.
- OpenRouter üzerinden model çağrısı yapılabiliyor.
- MongoDB Atlas Local üzerinde Wikontic ontology ve embedding indeksleri bulunuyor.
- Extraction job'ları artık ayrı bir Celery worker container'ında, Redis kuyruğu üzerinden asenkron işleniyor.
- Docker Compose ile mevcut sistem ayağa kaldırılabiliyor.

## Hedef mimari

```mermaid
flowchart LR
    U["Kullanıcı"] --> C["Caddy"]
    C --> F["React Frontend"]
    C --> G["FastAPI Gateway"]

    G --> P["PostgreSQL"]
    G --> R["Redis"]
    G --> Q["İş Kuyruğu"]

    Q --> W["Worker"]
    W --> WK["Wikontic"]
    W --> OR["OpenRouter"]
    WK --> M["MongoDB"]
    W --> S["S3 / MinIO"]
```

Teknoloji kararları:

- Frontend: mevcut React arayüzü
- Reverse proxy: Caddy
- API: FastAPI gateway
- Kalıcı uygulama verileri: PostgreSQL
- Session, rate limit, cache ve queue: Redis
- Ontology ve vector indeksleri: MongoDB
- Dosya deposu: geliştirmede Docker volume, üretimde S3/MinIO
- Worker ve zamanlanmış görevler: Celery ve Celery Beat
- LLM sağlayıcısı: OpenRouter

## Genel TODO

### 1. Kullanıcı girişi ve hesap oluşturma

Platform anonymous-first çalışacaktır. Kullanıcı giriş yapmadan triple çıkarabilecek ve aynı tarayıcıdan döndüğünde çalışma alanını görebilecektir.

- [x] Anonim ziyaretçi cookie'si oluşturma
- [x] Anonim çalışma alanı oluşturma
- [x] Kayıt, giriş, çıkış ve mevcut kullanıcı endpointleri
- [ ] E-posta doğrulama
- [ ] Şifre sıfırlama
- [x] Şifreleri Argon2id ile hashleme
- [x] HttpOnly server-side session kullanma
- [x] Anonim geçmişi kayıtlı hesaba aktarma
- [ ] Aktif oturumları görüntüleme ve kapatma
- [ ] Hesap ve kullanıcı verilerini silme
- [ ] Google/GitHub OAuth desteğini sonraki sürümde değerlendirme

### 2. Middleware

- [x] Her isteğe request ID verme
- [x] Request ID'yi downstream servislere aktarma
- [x] Güvenli JSON access ve hata logları
- [x] Merkezi ve standart hata cevapları
- [x] API anahtarı, cookie ve doküman içeriğini loglardan temizleme
- [x] Boş veya geçersiz içerikleri reddetme
- [x] Request boyutu sınırı
- [x] Environment tabanlı CORS ve Origin kontrolü
- [x] İmzalı anonim ziyaretçi cookie'si
- [x] Session doğrulama ve kullanıcı context'i
- [x] Güvenli upstream timeout yönetimi
- [x] Redis tabanlı rate limit
- [ ] Extraction concurrency limiti
- [x] Hash tabanlı duplicate kontrolü
- [x] Devam eden aynı işlemin tekrar başlatılmasını engelleme
- [x] Unit ve integration testleri

Temel middleware ve rate limit tamamlandı. Duplicate kontrolü doküman ve job modeliyle birlikte eklendi: doküman içeriği SHA-256 ile hashlenip aynı çalışma alanında tekrar kaydedilmiyor, extraction job'ları ise model, KG yöntemi, prompt, embedding modeli, ontology dili ve pipeline sürümünden üretilen bir fingerprint ile eşleşiyor; devam eden veya tamamlanmış aynı iş varsa yeniden kullanılıyor. Aynı anda gelen iki isteğin aynı job'ı iki kez oluşturması, uygulama seviyesindeki kontrole ek olarak `extraction_jobs` tablosundaki kısmi (partial) unique index ile veritabanı seviyesinde de engelleniyor.

### 3. Frontend

Mevcut tasarım korunacak ve yeni backend yeteneklerine bağlanacaktır.

- [x] Anonim oturum göstergesi
- [x] Giriş ve hesap oluşturma ekranları
- [ ] Anonim geçmişi hesaba aktarma akışı
- [ ] Text, PDF ve URL girişi
- [ ] Extraction job durumunu gösterme
- [ ] Bekliyor, çalışıyor, tamamlandı ve hata durumları
- [ ] Geçmiş doküman ve extraction listesi
- [ ] Triple detay ve kaynak kanıt görünümü
- [ ] RAG doğrulama ve consensus sonuçları
- [ ] Triple düzenleme, reddetme ve onaylama
- [ ] Sonuç indirme ve dışa aktarma
- [ ] Kullanım kotası ve model maliyet göstergesi
- [ ] Hatalarda request ID gösterme
- [ ] Veri kullanımı ve gizlilik bilgilendirmesi

### 4. Backend

Mevcut gateway korunacak ve modüler bir yapıya ayrılacaktır.

- [ ] `auth`, `documents`, `jobs`, `triples` ve `models` route'ları (auth, documents, extraction-jobs ve triples tamamlandı; models bekliyor)
- [ ] Text, PDF ve URL girişlerini ortak doküman modeline dönüştürme (ilk aşamada yalnızca düz metin destekleniyor)
- [x] Doküman hash'i ve pipeline fingerprint üretme
- [x] Extraction job oluşturma
- [x] Job'a tüm pipeline parametrelerini (model, kg_type, prompt_type, embedding_model, ontology_language) ve pipeline_version'ı kaydetme
- [x] Wikontic adapter katmanı
- [x] OpenRouter provider katmanı
- [ ] Model ve prompt ayarlarını doğrulama
- [x] Triple ve provenance kaydı
- [x] Candidate, verified ve rejected durumları
- [ ] RAG doğrulama akışı
- [ ] Çoklu model consensus ve final judge
- [ ] Global KG'ye yayınlama kontrolü
- [ ] API sürümleme
- [x] Mevcut senkron `/api/extract` endpoint'i için geçiş dönemi (aynı `extraction` servisini paylaşıyor, frontend job sistemine tam geçene kadar korunuyor)

### 5. Veritabanları

PostgreSQL uygulamanın ana kayıt kaynağı olacaktır. Redis geçici veri ve koordinasyon; MongoDB ise Wikontic ontology ve vector indeksleri için kullanılacaktır.

PostgreSQL tabloları:

- [x] `users`
- [x] `anonymous_visitors`
- [ ] `sessions`
- [x] `workspaces`
- [x] `documents`
- [x] `extraction_jobs`
- [x] `triples`
- [x] `triple_evidence`
- [ ] `verification_results`
- [ ] `pipeline_runs`
- [ ] `usage_records`
- [ ] `consent_records`

Altyapı işleri:

- [x] PostgreSQL Docker servisi
- [x] Redis Docker servisi
- [x] Alembic migration sistemi
- [ ] İndeksler ve unique constraint'ler
- [ ] Yedekleme politikası
- [ ] Veri silme ve saklama süreleri
- [ ] MongoDB profil ve index sağlık kontrolleri
- [ ] S3/MinIO dosya deposu entegrasyonu

### 6. Worker ve cron işlemleri

Uzun süren işlemler API container'ında çalıştırılmayacaktır.

Worker kuyrukları:

- [x] `extraction`: triple çıkarma
- [ ] `ingestion`: PDF, OCR, scraping ve metin temizleme
- [ ] `chunking`: parent-child chunk üretimi
- [ ] `verification`: RAG doğrulama
- [ ] `consensus`: çoklu model değerlendirmesi
- [ ] `publishing`: doğrulanmış triple'ları global KG'ye aktarma

Zamanlanmış görevler:

- [ ] Yarım kalan (crash sonrası `running` durumunda takılı kalmış) job'ları tespit edip yeniden kuyruğa alma
- [x] Başarısız job'ları sınırlı tekrar deneme (extraction worker içinde, geçici hatalar için — ayrı bir cron değil, task'ın kendi retry mekanizması)
- [ ] Süresi geçmiş session ve cache kayıtlarını temizleme
- [ ] Eski geçici dosyaları temizleme
- [ ] OpenRouter model listesini güncelleme
- [ ] Kullanım ve maliyet raporları üretme
- [ ] Candidate triple'ları periyodik benchmark'tan geçirme
- [ ] MongoDB ve embedding profillerinin sağlık kontrolü

Her job idempotent olmalıdır. Worker yeniden başlatıldığında aynı model çağrısı gereksiz yere tekrarlanmamalıdır.

## Önerilen geliştirme sırası

1. PostgreSQL ve Redis temeli
2. Temel middleware
3. Anonim ziyaretçi ve kullanıcı oturumları
4. Doküman, job ve triple backend API'leri
5. Worker ve queue sistemi
6. Frontend'in async job sistemine bağlanması
7. Duplicate önleme ve rate limit
8. RAG doğrulama ve çoklu model consensus
9. Cron görevleri, gözlemlenebilirlik ve üretim güvenliği

## Hesap API'si

Platform giriş zorunluluğu olmadan çalışır. İlk API isteğinde imzalı bir `kg_visitor` cookie'si oluşturulur. Kullanıcı kayıt olduğunda bu anonim ziyaretçi kullanıcı hesabına bağlanır ve Redis üzerinde `kg_session` oturumu açılır.

```text
GET  /api/auth/me
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
```

Kayıt isteği:

```json
{
  "email": "user@example.com",
  "password": "en-az-10-karakter",
  "display_name": "Kullanıcı Adı"
}
```

Giriş isteği:

```json
{
  "email": "user@example.com",
  "password": "en-az-10-karakter"
}
```

Cookie'ler `HttpOnly` ve `SameSite=Lax` olarak ayarlanır. Üretim ortamında HTTPS kullanın, güçlü bir secret üretin ve aşağıdaki değerleri değiştirin:

```bash
openssl rand -hex 32
```

```env
AUTH_COOKIE_SECRET=uretilen-deger
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_DOMAIN=example.com
```

PostgreSQL şeması backend başlarken Alembic tarafından otomatik uygulanır. Redis yalnızca giriş oturumlarını tutar; anonim ziyaretçi kimliği PostgreSQL'de kalıcıdır.

## Doküman ve extraction job API'si

Her anonim ziyaretçi veya kullanıcı için otomatik olarak bir çalışma alanı (`workspace`) oluşturulur. Kullanıcı giriş yaptığında, anonim oturumdaki çalışma alanı otomatik olarak hesaba taşınır.

```text
POST /api/documents
GET  /api/documents
GET  /api/documents/{id}

POST /api/extraction-jobs
GET  /api/extraction-jobs/{id}
```

Doküman oluşturma isteği:

```json
{
  "text": "İşlenecek düz metin",
  "title": "Opsiyonel başlık"
}
```

Gönderilen metin normalize edilir (Unicode NFC, satır sonu ve boşluk temizliği) ve SHA-256 ile hashlenir. Aynı çalışma alanında aynı içerik hash'ine sahip bir doküman zaten varsa yeni kayıt açılmaz, mevcut doküman `200` ile döndürülür; yeni bir doküman oluşturulduğunda cevap `201` olur.

Extraction job oluşturma isteği:

```json
{
  "document_id": "...",
  "model": "openrouter/model-id",
  "prompt_type": "temel",
  "kg_type": "wikipedia",
  "embedding_model": "contriever",
  "ontology_language": "en"
}
```

Bu parametrelerden (`kg_type`, `prompt_type`, `embedding_model`, `ontology_language`, `model`, `pipeline_version`) bir pipeline fingerprint üretilir. Aynı doküman için aynı fingerprint'e sahip `queued`, `running` veya `completed` durumunda bir job zaten varsa yeni job açılmaz, mevcut job `200` ile döndürülür; yeni job oluşturulduğunda cevap `201` ve durum `queued` olur. Başarısız (`failed`) job'lar için yeniden deneme yeni bir job kaydı açar.

`extraction_jobs` tablosu, worker'ın işi nasıl çalıştıracağını bilmesi için gönderilen tüm pipeline parametrelerini (`model`, `kg_type`, `prompt_type`, `embedding_model`, `ontology_language`) ve şemadaki `pipeline_version`'ı ayrı sütunlarda saklar; job cevabında bu alanlar da döner. Aynı doküman + aynı fingerprint için aktif (`queued`/`running`) birden fazla job açılmasını, uygulama kontrolüne ek olarak veritabanındaki kısmi unique index kesin olarak engeller; iki eşzamanlı istek çakışırsa ikincisi mevcut job'ı yeniden kullanır.

Job oluşturulduğunda (yeni bir kayıt açıldıysa) job kimliği Celery üzerinden `extraction-worker` container'ına gönderilir; işleme aşağıdaki "Extraction worker" bölümünde anlatılmaktadır.

## Triple ve provenance API'si

Bir extraction job tamamlandığında çıkarılan triple'lar `triples` tablosunda, bu triple'ların hangi kaynak metinden geldiği ise `triple_evidence` tablosunda saklanır. Her triple `document_id`, `extraction_job_id` ve `workspace_id` ile ilişkilendirilir; böylece bir triple'ın hangi dokümandan, hangi işten ve hangi çalışma alanından geldiği izlenebilir.

```text
GET   /api/extraction-jobs/{job_id}/triples
GET   /api/triples/{triple_id}
PATCH /api/triples/{triple_id}/status
```

Triple durumları: `candidate` (varsayılan), `verified`, `rejected`. Durum güncelleme isteği:

```json
{
  "status": "verified"
}
```

Triple cevabı, kaynak paragraf/cümle metnini ve doküman içindeki karakter konumunu (`char_start`, `char_end`) içeren bir `evidence` listesi döndürür:

```json
{
  "id": "...",
  "subject": "Atatürk",
  "predicate": "doğum_yeri",
  "object": "Selanik",
  "status": "candidate",
  "evidence": [
    { "source_text": "Atatürk 1881 yılında Selanik'te doğdu.", "char_start": 0, "char_end": 38 }
  ]
}
```

Triple oluşturma genel bir endpoint üzerinden yapılmaz; bunun yerine extraction worker, işi tamamladığında sonuçları doğrudan iç servis katmanı (`triples.service`) üzerinden kaydeder. Tüm triple endpointleri, dokümanlar ve job'larla aynı çalışma alanı (workspace) erişim kontrolüne tabidir; başka bir kullanıcıya/ziyaretçiye ait triple'lara erişim `404` döner.

## Extraction worker

`POST /api/extraction-jobs` ile yeni bir job açıldığında, gateway job kimliğini (yalnızca kimliği — metin veya pipeline parametreleri değil) Redis üzerinden Celery kuyruğuna gönderir. Ayrı bir `extraction-worker` container'ı bu kuyruğu tüketir:

```text
POST /api/extraction-jobs
        ↓
PostgreSQL: queued
        ↓
Redis/Celery kuyruğu (yalnızca job_id taşınır)
        ↓
Worker job'ı atomik olarak sahiplenir (queued → running)
        ↓
extraction.service.run_extraction → Wikontic adapter'ı veya OpenRouter provider'ı çalıştırır
        ↓
Triple + evidence kaydeder (mevcut kayıtların yerine geçer)
        ↓
completed / failed
```

Mimari notları:

- **Ortak extraction servisi.** `extraction/` paketi (`wikontic_adapter.py`, `openrouter_provider.py`, `service.py`) hem senkron `/api/extract` endpoint'i hem de worker tarafından kullanılır; iki kod yolu birbirinden sapmaz. `kg_type=wicontic` Wikontic adapter'ına, `kg_type` `wikipedia`/`kggen` ise OpenRouter provider'ına yönlenir.
- **Atomik sahiplenme.** Worker bir job'ı işlemeden önce `UPDATE extraction_jobs SET status='running' WHERE id=... AND status='queued'` ile atomik olarak sahiplenir. Bu sorgu 0 satır etkilerse (başka bir worker zaten almış ya da job zaten `completed`/`failed`) worker sessizce çıkar — mesaj tekrar teslim edilse bile (Redis'in "en az bir kez teslim" garantisi) job iki kez işlenmez.
- **İdempotent yazım.** Worker sonuçları yazarken o job'a ait önceki triple/evidence kayıtlarını silip yenilerini ekler (`triples.service.replace_triples_for_job`). Bir görev yarıda kalıp yeniden denendiğinde veya mesaj tekrar teslim edildiğinde triple'lar çoğalmaz.
- **Durum geçişleri ve zaman damgaları.** `queued → running → completed` veya `queued → running → failed`. `started_at` sahiplenme anında, `completed_at` sonuç ne olursa olsun (başarı/başarısızlık) yazılır. Başarısızlıkta `error_message` insan tarafından okunabilir, güvenli (iç detay/secret sızdırmayan) bir mesajla doldurulur.
- **Sınırlı retry.** Geçici hatalar (zaman aşımı, 5xx, ağ hatası) `EXTRACTION_JOB_MAX_RETRIES` (varsayılan 3) kez, `EXTRACTION_JOB_RETRY_BACKOFF_SECONDS` (varsayılan 30) bekleme ile tekrar denenir. Kalıcı hatalar (bilinmeyen `kg_type`, 4xx doğrulama hataları) hiç denenmeden `failed` olarak işaretlenir.
- **Broker erişilemezse job kaybolmaz.** Job her zaman önce PostgreSQL'e `queued` olarak yazılır; Celery'ye gönderim (`.delay()`) ayrı bir adımdır ve başarısız olursa (broker geçici olarak erişilemezse) yalnızca loglanır — job satırı `queued` durumda kalıcı olarak durur ve API isteği yine de başarıyla döner. Bu job'ları otomatik olarak yeniden kuyruğa alan zamanlanmış görev (stale job sweep) henüz eklenmedi; bu iş "Worker ve cron işlemleri" bölümünde plânlanmıştır.
- **Concurrency.** Worker container'ı `--concurrency=${CELERY_WORKER_CONCURRENCY:-2}` ile başlar.

Ortam değişkenleri (`.env.example`):

```env
CELERY_WORKER_CONCURRENCY=2
CELERY_TASK_TIME_LIMIT_SECONDS=300
CELERY_TASK_SOFT_TIME_LIMIT_SECONDS=270
EXTRACTION_JOB_MAX_RETRIES=3
EXTRACTION_JOB_RETRY_BACKOFF_SECONDS=30
```

Testler: `tests/test_extraction.py` (adapter/provider/dispatch birim testleri), `tests/test_worker_tasks.py` (Celery `task_always_eager` ile başarı, tekrar teslimde no-op, yarıda kalan işin idempotent yeniden yazımı, kalıcı/geçici hata senaryoları) ve `tests/test_worker_redis_integration.py` (gerçek bir Redis broker'a karşı `celery.contrib.testing.worker.start_worker` ile uçtan uca job teslimi — Redis erişilemezse otomatik `skip` edilir, `REDIS_TEST_URL` ile hedef broker değiştirilebilir).

## Middleware davranışı

Gateway bütün API isteklerine bir `X-Request-ID` verir ve bu kimliği Wikontic çağrılarına aktarır. Hata cevapları aynı sözleşmeyi kullanır:

```json
{
  "detail": "İnsan tarafından okunabilir açıklama",
  "error": {
    "code": "VALIDATION_ERROR",
    "request_id": "req_..."
  }
}
```

Middleware şu kontrolleri gateway seviyesinde uygular:

- JSON access/error logları; cookie, API anahtarı ve istek gövdesi loglanmaz.
- İzin verilen origin, JSON content type ve maksimum istek boyutu kontrolü.
- Redis üzerinde IP bazlı, sabit zaman pencereli genel API, auth ve extraction limitleri.
- `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` ve gerektiğinde `Retry-After` başlıkları.
- Redis rate limit servisi kullanılamıyorsa korunan endpoint için güvenli `503` cevabı.
- Upstream bağlantı ve zaman aşımı hatalarında iç ayrıntıları gizleyen `502/504` cevapları.

Yerel varsayılanlar `.env.example` içindedir. Üretimde en az aşağıdaki değerleri ortama göre değiştirin:

```env
ALLOWED_ORIGINS=https://uygulama.example.com
MAX_REQUEST_BYTES=2097152
TRUST_PROXY_HEADERS=true
LOG_HASH_SALT=uzun-rastgele-bir-deger
RATE_LIMIT_ENABLED=true
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_GENERAL_REQUESTS=120
RATE_LIMIT_AUTH_REQUESTS=10
RATE_LIMIT_EXTRACT_REQUESTS=10
```

`TRUST_PROXY_HEADERS=true` yalnızca backend doğrudan internete açılmadığında ve istekler güvenilen Caddy katmanından geçtiğinde kullanılmalıdır.

## Çalıştırma

Gerekenler: Docker Desktop ve OpenRouter API anahtarı.

İlk kurulum:

```bash
cp .env.example .env
```

`.env` dosyasına OpenRouter anahtarını yazın:

```env
OPENROUTER_API_KEY=your_api_key
```

RAG verilerini bir kez hazırlayın:

```bash
docker compose --profile setup run --rm wikontic-init
```

Frontend ve backend servislerini başlatın:

```bash
docker compose up -d --build
```

Uygulama adresi: http://localhost:3000

Servisleri durdurun:

```bash
docker compose down
```

Sonraki çalıştırmalarda:

```bash
docker compose up -d
```
