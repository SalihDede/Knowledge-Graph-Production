# Knowledge Graph Production

Genel bilgi grafiği çıkarmak ve doğrulanmış triple veri seti oluşturmak için geliştirilmiştir.

## Çalıştırma

Gerekenler: Docker Desktop ve OpenRouter API anahtarı.

İlk kurulum:

```bash
cp .env.example .env
```

`.env` dosyasına anahtarınızı yazın:

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

Uygulamayı açın: http://localhost:3000

Servisleri durdurmak için:

```bash
docker compose down
```

Sonraki çalıştırmalarda yalnızca şu komut yeterlidir:

```bash
docker compose up -d
```