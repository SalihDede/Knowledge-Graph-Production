# Knowledge Graph Production

Metin, PDF ve web kaynaklarından bilgi grafiği çıkarmak; üretilen triple'ları RAG ve çoklu model değerlendirmesiyle doğrulamak; doğrulanmış bir triple veri seti oluşturmak için geliştirilen platformdur.

## Mevcut durum

- React frontend Caddy üzerinden çalışıyor.
- FastAPI gateway, frontend API sözleşmesini sağlıyor.
- Wikontic ayrı bir servis olarak çalışıyor.
- OpenRouter üzerinden model çağrısı yapılabiliyor.
- MongoDB Atlas Local üzerinde Wikontic ontology ve embedding indeksleri bulunuyor.
- Extraction job'ları artık ayrı bir Celery worker container'ında, Redis kuyruğu üzerinden asenkron işleniyor.
- Ayrı bir Celery Beat container'ı, kaybolan/takılı kalan job'ları periyodik olarak tarayıp kurtarıyor.
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
- [x] Extraction concurrency limiti (workspace başına maksimum eşzamanlı `queued`/`running` job)
- [x] Hash tabanlı duplicate kontrolü
- [x] Devam eden aynı işlemin tekrar başlatılmasını engelleme
- [x] Unit ve integration testleri

Temel middleware ve rate limit tamamlandı. Duplicate kontrolü doküman ve job modeliyle birlikte eklendi: doküman içeriği SHA-256 ile hashlenip aynı çalışma alanında tekrar kaydedilmiyor, extraction job'ları ise model, KG yöntemi, prompt, embedding modeli, ontology dili ve pipeline sürümünden üretilen bir fingerprint ile eşleşiyor; devam eden veya tamamlanmış aynı iş varsa yeniden kullanılıyor. Aynı anda gelen iki isteğin aynı job'ı iki kez oluşturması, uygulama seviyesindeki kontrole ek olarak `extraction_jobs` tablosundaki kısmi (partial) unique index ile veritabanı seviyesinde de engelleniyor.

### 3. Frontend

Mevcut tasarım korunacak ve yeni backend yeteneklerine bağlanacaktır.

- [x] Anonim oturum göstergesi
- [x] Giriş ve hesap oluşturma ekranları
- [x] Anonim geçmişi hesaba aktarma akışı (giriş yapınca aynı workspace geçmişi otomatik görünür, bkz. "Workspace geçmişi ve triple review")
- [ ] Text, PDF ve URL girişi
- [x] Extraction job durumunu gösterme (doküman → job → polling → triple akışı, bkz. "Frontend async extraction akışı")
- [x] Bekliyor, çalışıyor, tamamlandı ve hata durumları (`queued`/`running` → "Çalışıyor", `completed` → "Hazır", `failed` → "Hata")
- [x] Geçmiş doküman ve extraction listesi (sidebar'daki Geçmiş paneli)
- [x] Triple detay ve kaynak kanıt görünümü (Triple İnceleme penceresi, `char_start`/`char_end` vurgulamalı)
- [ ] RAG doğrulama ve consensus sonuçları
- [x] Triple düzenleme, reddetme ve onaylama
- [ ] Sonuç indirme ve dışa aktarma
- [ ] Kullanım kotası ve model maliyet göstergesi
- [x] Hatalarda request ID gösterme
- [ ] Veri kullanımı ve gizlilik bilgilendirmesi

### 4. Backend

Mevcut gateway korunacak ve modüler bir yapıya ayrılacaktır.

- [x] `auth`, `documents`, `jobs`, `triples` ve `models` route'ları (`models` artık ayrı bir `catalog` modülünde)
- [ ] Text, PDF ve URL girişlerini ortak doküman modeline dönüştürme (ilk aşamada yalnızca düz metin destekleniyor)
- [x] Doküman hash'i ve pipeline fingerprint üretme
- [x] Extraction job oluşturma
- [x] Job'a tüm pipeline parametrelerini (model, kg_type, prompt_type, embedding_model, ontology_language) ve pipeline_version'ı kaydetme
- [x] Wikontic adapter katmanı
- [x] OpenRouter provider katmanı
- [x] Model ve prompt ayarlarını doğrulama (OpenRouter allow-list + kg_type/prompt_type/embedding_model/ontology_language kombinasyon kontrolü, bkz. "Extraction policy" bölümü)
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

- [x] Yarım kalan (crash sonrası `running` durumunda takılı kalmış) veya hiç gönderilememiş (`queued` durumunda takılı kalmış) job'ları tespit edip yeniden kuyruğa alma — Celery Beat, bkz. "Job recovery scheduler"
- [x] Başarısız job'ları sınırlı tekrar deneme (hem worker içindeki geçici-hata retry'ı, hem recovery scheduler'ın `JOB_RECOVERY_MAX_ATTEMPTS` sınırı)
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
GET  /api/extraction-jobs
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

Job oluşturmadan önce istek "Extraction policy" bölümünde açıklanan kontrollerden geçer: geçersiz `kg_type`/`prompt_type`/`embedding_model`/`ontology_language` veya izin verilmeyen `model` `422` ile, çalışma alanı başına aktif iş limiti aşımı `429` ile reddedilir — bu durumlarda job hiç oluşturulmaz.

`GET /api/extraction-jobs`, çağıran kimliğin (ziyaretçi ya da kullanıcı) çalışma alanına ait job geçmişini döndürür — en yeni önce. Sorgu parametreleri:

```text
?limit=50          # 1-200 arası, varsayılan 50
&offset=0
&status=completed  # queued | running | completed | failed
&document_id=...
```

Cevaptaki her satır (`ExtractionJobSummary`) doküman başlığını, ilk ~200 karakterlik bir önizlemeyi ve o job'a ait triple sayısını içerir; dokümanın tam `raw_text`/`normalized_text` içeriğini **hiçbir zaman** döndürmez — bunun için ayrıca `GET /api/documents/{id}` çağrılmalıdır. Liste her zaman çağıranın kendi çalışma alanına göre filtrelenir; başka bir workspace'in job'ları hiçbir koşulda görünmez.

## Extraction policy

API'ye keyfi bir OpenRouter modeli, pipeline kombinasyonu veya sınırsız sayıda eşzamanlı iş gönderilmesini engelleyen bir koruma katmanı vardır. Bu kontroller hem `POST /api/extract` hem de `POST /api/extraction-jobs` için geçerlidir ve `Backend/gateway/policy.py` + `Backend/gateway/catalog/` içinde toplanmıştır.

Model kataloğu artık ayrı bir modülde:

```text
GET /api/models
```

`allowedOpenroutherLLMModels.json` içindeki liste, izin verilen OpenRouter modellerinin tek doğruluk kaynağıdır (allow-list). Gönderilen `model` bu listede yoksa istek `422` ile reddedilir.

Anonim (giriş yapmamış) ziyaretçiler için ayrıca daha dar bir alt küme uygulanır — maliyet kontrolü amacıyla, kayıtlı kullanıcı olmayan biri yalnızca `ANONYMOUS_MODEL_ALLOWLIST` içindeki modelleri kullanabilir (varsayılan: tek, ucuz bir model). Bu liste her zaman tam kataloğun bir alt kümesidir; env değişkeni yanlışlıkla kataloğa hiç girmemiş bir model id'si içerse bile o id yok sayılır.

Pipeline kombinasyonu doğrulaması:

- `kg_type`: `wikipedia`, `wicontic`, `kggen`
- `prompt_type`: `temel`, `ape`, `dspy`, `textgrad`
- `embedding_model`: `contriever`, `bge_m3`, `turkish_e5_large`, `turkish_sbert_mean_nli_stsb`, `mft_random`
- `ontology_language`: `en`, `tr`

Bu kümelerin dışında bir değer, ya da izin verilmeyen bir `model`, job/extract isteğini `422` ile reddeder — job hiçbir zaman oluşturulmaz.

Metin uzunluğu ve iş kotası:

- `MAX_EXTRACTION_CHARS` (varsayılan `100000`): hem `POST /api/documents` (pydantic `max_length` ile) hem `POST /api/extract` bu sınırı aşan metni `422` ile reddeder.
- `MAX_ACTIVE_JOBS_PER_WORKSPACE` (varsayılan `3`): bir çalışma alanının aynı anda sahip olabileceği `queued`/`running` job sayısının üst sınırıdır. Zaten var olan bir job'ın yeniden kullanılması (dedup) bu sayaca dahil değildir — yalnızca gerçekten yeni bir job açmaya çalışan istekler sayılır ve limit aşıldığında `429` döner. Bu, uygulama seviyesinde bir kontrol say/ekle sırasına dayanır (yarış koşulunda küçük bir toleransla) — kesin bir veritabanı kısıtı değildir; amaç kötüye kullanımı/maliyeti sınırlamaktır, tam bir eşzamanlılık garantisi değildir.

Ortam değişkenleri (`.env.example`):

```env
MAX_EXTRACTION_CHARS=100000
MAX_ACTIVE_JOBS_PER_WORKSPACE=3
ANONYMOUS_MODEL_ALLOWLIST=google/gemini-2.5-flash-lite
```

Testler: `tests/test_policy.py` (allow-list, anonim alt küme, pipeline doğrulama, metin uzunluğu — birim testleri), `tests/test_catalog.py` (`/api/models` sözleşmesi), `tests/test_documents.py` ve `tests/test_api.py` içindeki uçtan uca `422`/`429` senaryoları.

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
- **Broker erişilemezse job kaybolmaz.** Job her zaman önce PostgreSQL'e `queued` olarak yazılır; Celery'ye gönderim (`.delay()`) ayrı bir adımdır ve başarısız olursa (broker geçici olarak erişilemezse) yalnızca loglanır — job satırı `queued` durumda kalıcı olarak durur ve API isteği yine de başarıyla döner. Bu job'lar ve çökmüş worker'lar yüzünden `running`'de takılı kalan job'lar, ayrı bir Celery Beat container'ının periyodik taramasıyla otomatik olarak kurtarılır; bkz. "Job recovery scheduler" bölümü.
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

## Job recovery scheduler

Extraction worker altyapısının kapattığı iki risk hâlâ açıktı: Redis broker geçici olarak kapalıyken oluşturulan bir job'un mesajı hiç yayınlanamayabilir (`queued` durumunda sonsuza dek takılı kalır), ve worker bir job'ı işlerken çökerse job `running` durumunda asılı kalabilir. Ayrı bir `celery-beat` container'ı, periyodik bir tarama görevi (`worker.tasks.recover_stale_jobs`) ile bu iki durumu tespit edip kurtarır:

```text
Celery Beat  (JOB_RECOVERY_SWEEP_SECONDS'te bir tetikler)
    ↓
recover_stale_jobs task'ı  (bir extraction-worker sürecinde çalışır)
    ↓
Stale job taraması (worker/recovery.py::sweep_stale_jobs)
    ├── queued ama QUEUED_JOB_STALE_SECONDS'ten uzun süredir bekliyor → yeniden enqueue
    └── running ama RUNNING_JOB_STALE_SECONDS'ten uzun süredir başlamış → queued'a al → yeniden enqueue
```

Mimari notları:

- **Beat yalnızca zamanlayıcı.** `celery-beat` container'ı veritabanına hiç dokunmaz; sadece `recover_stale_jobs` görevini Redis kuyruğuna belirli aralıklarla yayınlar. Görevin kendisi, normal extraction job'ları gibi mevcut `extraction-worker` süreçlerinden biri tarafından tüketilir ve gerçek veritabanı işini orada yapar.
- **Atomik ve tekilleştirilmiş seçim.** `sweep_stale_jobs`, aday satırları `SELECT ... FOR UPDATE SKIP LOCKED` ile kilitler (`JOB_RECOVERY_BATCH_SIZE` kadar, en eski önce). Aynı anda ikinci bir Beat/worker replikası aynı taramayı çalıştırırsa, kilitli satırları atlar — aynı job iki scheduler tarafından aynı anda kurtarılamaz. (SQLite bu kilidi no-op'a çevirir; birim testleri onun üzerinden çalışır, gerçek kilitleme davranışı ayrı bir PostgreSQL entegrasyon testiyle doğrulanır.)
- **Sınırlı deneme sayısı.** Her job'un kendi `recovery_attempts` sayacı vardır. Bir kurtarma denemesi bu sayacı `JOB_RECOVERY_MAX_ATTEMPTS`'i aşacaksa job yeniden kuyruğa alınmaz; bunun yerine doğrudan `failed` yapılır ve `error_message` alanına güvenli, sabit bir mesaj yazılır — sürekli sorun çıkaran bir job sonsuza dek denenmez.
- **Duplicate triple üretmez.** Kurtarma yalnızca job'un `status`/`started_at` alanlarını sıfırlar; gerçek yeniden işleme, worker'ın zaten idempotent olan `replace_triples_for_job` (sil-ve-yeniden-yaz) akışından geçer, bu yüzden bir job kaç kez kurtarılırsa kurtarılsın triple çoğalmaz.
- **Log korelasyonu.** Her tarama turu bir `sweep_id` (uuid4) üretir; o turda kurtarılan/başarısız sayılan her job, log satırında hem kendi `job_id`'si hem de bu ortak `sweep_id` ile birlikte görünür.
- **Bilinen sınır.** Gerçekten uzun süren meşru bir extraction (ör. çok büyük bir doküman), `RUNNING_JOB_STALE_SECONDS`'i aşarsa yanlışlıkla "çökmüş" sayılıp kurtarılabilir. Varsayılan değer (600 sn) bunu nadir kılacak şekilde seçildi; worker'dan gerçek bir heartbeat sinyali bu sınırı tamamen ortadan kaldırır ama bu görevin kapsamı dışında bırakıldı.

Ortam değişkenleri (`.env.example`):

```env
JOB_RECOVERY_SWEEP_SECONDS=60
QUEUED_JOB_STALE_SECONDS=120
RUNNING_JOB_STALE_SECONDS=600
JOB_RECOVERY_MAX_ATTEMPTS=3
JOB_RECOVERY_BATCH_SIZE=100
```

`extraction_jobs` tablosuna bu özellik için iki sütun eklendi: `recovery_attempts` (kaç kez kurtarılmaya çalışıldığı) ve `last_recovery_at` (son kurtarma denemesinin zamanı — bir sonraki taramanın "ne zamandan beri stale" hesabının referans noktası). Her iki alan da `GET /api/extraction-jobs/{id}` cevabında da döner.

Testler: `tests/test_job_recovery.py` (SQLite birim testleri — taze job'un dokunulmadan kalması, stale queued/running job'ların kurtarılması, max deneme aşımında `failed`'e düşme, batch boyutu sınırı, tamamlanmış/başarısız job'lara dokunulmaması) ve `tests/test_job_recovery_postgres_integration.py` (gerçek PostgreSQL'e karşı — temel kurtarma akışı ve `FOR UPDATE SKIP LOCKED`'ın iki scheduler'ın aynı job'u aynı anda kurtarmasını engellediğinin doğrulanması). PostgreSQL erişilemezse bu testler otomatik `skip` edilir; `POSTGRES_TEST_URL` ile hedef veritabanı değiştirilebilir.

## Frontend async extraction akışı

Studio arayüzü artık senkron `/api/extract` yerine doküman/job akışını kullanır (mevcut UI tasarımı ve Türkçe triple alanları — `baş`/`ilişki`/`uç` — değişmedi; sadece veri kaynağı değişti). `Frontend/src/App.jsx` içindeki `handleGraphSend` bir sonuç kartı için şu adımları izler:

```text
POST /api/documents  (metni kaydet)
        ↓
POST /api/extraction-jobs  (job'ı başlat)
        ↓
GET /api/extraction-jobs/{id}  (2.5 sn'de bir poll)
        ↓
queued / running  → kart "Çalışıyor" (loading) gösterir
        ↓
completed         → GET /api/extraction-jobs/{id}/triples çağrılır
        ↓
failed            → hata mesajı + istek kimliği (X-Request-ID) gösterilir
```

İlgili dosyalar:

- `Frontend/src/api/extraction.js` — `createDocument`, `createExtractionJob`, `getExtractionJob`, `getJobTriples`, `getDocument` istemcileri ve backend triple şemasını (`subject`/`predicate`/`object`/`evidence`) mevcut Türkçe UI şemasına (`baş`/`ilişki`/`uç`/`kaynak_cumle`) çeviren `mapTriplesToLegacyFormat`.
- `Frontend/src/api/activeJobsStorage.js` — aktif (henüz `completed`/`failed` olmamış) job kimliklerini `localStorage`'da tutar; sayfa yenilendiğinde `App.jsx`'teki mount effect'i bu kimlikleri okuyup job + doküman durumunu tekrar çekerek kartları geri kurar, terminal duruma ulaşan job'lar listeden otomatik çıkarılır.
- Polling tek bir `setInterval` (2.5 sn) ile yürütülür ve yalnızca `queued`/`running` durumundaki kartları sorgular; `useEffect` temizleme fonksiyonu component unmount olduğunda (sayfadan ayrılınca) interval'ı durdurur.
- Job oluşturma anında zaten `completed`/`failed` dönerse (aynı pipeline için mevcut bir job'un yeniden kullanılması durumunda) sonuç ilk poll turunu beklemeden hemen işlenir.
- Başarısız (`failed`) durumda kart hem `error_message`'ı hem de o anki HTTP cevabının `X-Request-ID` başlığını gösterir.

Testler: `Frontend/src/api/extraction.test.js` (triple eşleme, durum eşleme, süre hesaplama, `buildCardFromJob`, API istemcisi — `fetch` mock'lanarak) ve `Frontend/src/api/activeJobsStorage.test.js` (localStorage kalıcılığı, bozuk veri/geçersiz kayıtlara dayanıklılık). Çalıştırmak için:

```bash
cd Frontend
npm install
npm test
```

## Workspace geçmişi ve triple review

Tamamlanmış job'lar PostgreSQL'de kalıcı olarak durur; sayfa yenilendiğinde (ve daha önce `localStorage`'da hiç iz bırakmamış eski job'lar için de) kullanıcı bunlara sidebar'daki **Geçmiş** panelinden ulaşabilir. Bu panel `GET /api/extraction-jobs` listesini gösterir ve şu durumları ayrı ayrı ele alır:

- **Loading**: `t.historyPanel.loading` metni.
- **Empty**: hiç job yoksa `t.historyPanel.empty`.
- **Error**: istek başarısız olursa hata mesajı + varsa `X-Request-ID` gösterilir; "Yenile" butonu tekrar dener.
- Her satır doküman başlığını/önizlemesini, durumunu (Sırada/Çalışıyor/Tamamlandı/Hata) ve triple sayısını gösterir.

Bir geçmiş satırına tıklamak (`handleSelectHistoryJob` — `App.jsx`), o job'un dokümanını (`GET /api/documents/{id}`) ve — tamamlanmışsa — triple'larını (`GET /api/extraction-jobs/{id}/triples`) çekip mevcut sonuç kartı bileşenini (`ResultCard`) aynı şekilde yeniden oluşturur; en fazla 3 aktif kart sınırı burada da geçerlidir.

Geçmiş, `identity` her değiştiğinde (giriş/çıkış) otomatik olarak yeniden yüklenir. Bunun için herhangi bir özel senkronizasyon gerekmez: backend zaten workspace'i oturum/ziyaretçi çerezinden çözer ve kullanıcı giriş yaptığında ziyaretçinin çalışma alanını hesaba taşır (bkz. "Doküman ve extraction job API'si"), dolayısıyla aynı `GET /api/extraction-jobs` isteği artık aynı geçmişi yeni kimlik altında döndürür — anonim geçmiş kaybolmaz.

Tamamlanmış bir kartın başlığındaki onay ikonu **Triple İnceleme** penceresini açar (`TripleReviewModal.jsx`):

- Sol sütun: job'un tüm triple'ları, durum rozetleriyle (Aday/Onaylandı/Reddedildi) birlikte.
- Sağ sütun: seçili triple'ın kaynak kanıtları — dokümanın tam metni içinde, triple'ın `char_start`/`char_end` aralığı `<mark>` ile vurgulanarak gösterilir.
- Her triple için üç aksiyon: **Onayla** (`PATCH .../status` → `verified`), **Reddet** (→ `rejected`), **Geri al** (→ `candidate`). Güncelleme başarılı olduğunda kartın hem `rawTriples`'ı hem de KG grafiğinde kullanılan eşlenmiş `triplets`'ı yerinde güncellenir; başarısız olursa modalde bir hata mesajı gösterilir.

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
