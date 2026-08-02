# Bilgi Grafiği Üreteci - UI Akış Dokümantasyonu

Referans: `refImages/image.png`, `refImages/image2.png`, `refImages/image3.png`

---

## Genel Yapı

Tek sayfalı uygulama. Kullanıcı aynı kart üzerinde ilerler, kart state'e göre dönüşür.
Maksimum **3 graph** üretilebilir.

---

## Adım 1 — Başlangıç Kartı (`image.png` sol)

```
┌──────────────────────────────────────┐
│  Başlık                              │
│  Kısa Açıklama                       │
│                                      │
│  [LLM Modeli Seçin ▼]                │
│  ┌──────────────────────────────┐    │
│  │  TEXT Buraya Gelecek         │    │
│  └──────────────────────────────┘    │
│                                0/3   │
│                                      │
│   Bilgi Grafiği Oluşturmaya          │
│       Başlamak İçin Tıkla            │  ← CTA tıklanır → Adım 2
└──────────────────────────────────────┘
```

**Elementler:**
- Başlık + Kısa Açıklama (statik metin)
- LLM Model dropdown (seçim)
- Büyük metin alanı (kullanıcı text girer)
- Sağ alt: `0/3` sayacı
- Alt orta: büyük tıklanabilir metin → **"Bilgi Grafiği Oluşturmaya Başlamak İçin Tıkla"**

**Tıklama:**
- CTA metnine tıklanır
- Kart Adım 2 görünümüne geçer (model ve metin korunur)

---

## Adım 2 — Teknik & Optimizasyon Seçimi (`image.png` sağ, `image2.png`)

```
┌────────────────────────────────────────────────────┐
│  Başlık                                            │
│  Kısa Açıklama                                     │
│                                                    │
│  [Gemma 4            ]                             │
│  ┌──────────────────────────────────────────┐      │
│  │ Atatürk, türk komutandır.                │      │
│  └──────────────────────────────────────────┘      │
│                                                    │
│  [Kullanmak İstediğiniz Teknik ▼] ←─┐              │
│  [Kullanmak İstediğiniz Opt.    ▼] ←┘  +  [0/3]   │  ← + tıklanır
│                                                    │
│  (graph kartları burada eklenir)                   │
└────────────────────────────────────────────────────┘
```

**Elementler:**
- Model ve metin alanı korunur (Adım 1'den taşınır)
- 2 mavi dropdown butonu görünür: **Teknik** + **Optimizasyon**
- **`+` butonu** — tıklanınca yeni graph kartı ekler
- Sayaç: `X/3` (0'dan 3'e çıkar)

**Tıklama — `+` butonu:**
- Seçili Teknik + Optimizasyon alınır
- Yeni `GraphCard` bileşeni oluşturulur ve listeye eklenir
- Sayaç `+1` artar
- Sayaç `3/3` olduğunda `+` butonu **disabled** olur

---

## GraphCard Bileşeni

```
┌──────────────────────────────────────┐
│ [Sil]                                │
│                                      │
│  Oluşan Graph N                      │
│  Seçilen Teknik: Teknik X            │
│  Seçilen Opt: Opt Y                  │
│                                      │
│  (graph içeriği buraya gelecek)      │
└──────────────────────────────────────┘
```

**Elementler:**
- Sol üst: **`Sil`** butonu
- İçerik: Graph numarası + seçilen teknik + seçilen optimizasyon
- Alt alan: Graph verisi (şimdilik boş)

**Tıklama — `Sil` butonu:**
- O kart listeden çıkarılır
- Sayaç `−1` azalır
- Kalan kartlar yeniden numaralandırılır (1, 2, 3...)

---

## Adım 3 — 3/3 Dolu Durum (`image3.png`)

```
┌────────────────────────────────────────────────────────────────┐
│  [Gemma 4] + input text                                        │
│  [Teknik ▼]  [Opt ▼]  +  [3/3]   ← + butonu disabled         │
│                                                                │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐     │
│  │ [Sil]          │ │ [Sil]          │ │ [Sil]          │     │
│  │                │ │                │ │                │     │
│  │ Graph 1        │ │ Graph 2        │ │ Graph 3        │     │
│  │ Teknik 1       │ │ Teknik 2       │ │ Teknik 3       │     │
│  │ Opt 1          │ │ Opt 2          │ │ Opt 3          │     │
│  └────────────────┘ └────────────────┘ └────────────────┘     │
└────────────────────────────────────────────────────────────────┘
```

**Kurallar:**
- 3 kart yan yana sıralanır
- `+` butonu disabled (görünür ama tıklanamaz)
- `Sil` ile bir kart silinirse `+` tekrar aktif olur

---

## State Özeti

| State          | Tip       | Açıklama                              |
|----------------|-----------|---------------------------------------|
| `step`         | `1 \| 2`  | Hangi adımda olduğu                   |
| `selectedModel`| `string`  | Seçilen LLM modeli                    |
| `inputText`    | `string`  | Girilen metin                         |
| `graphs`       | `array`   | Eklenen graph kartları (max 3)        |
| `selectedTech` | `string`  | Seçili teknik (dropdown)              |
| `selectedOpt`  | `string`  | Seçili optimizasyon (dropdown)        |

---

## Tıklama Haritası (Özet)

```
CTA Metni         → step: 1 → 2
+ Butonu          → graphs.push({teknik, opt})  — max 3
Sil Butonu        → graphs.splice(i, 1)
Teknik Dropdown   → selectedTech güncelle (boş handler)
Opt Dropdown      → selectedOpt güncelle (boş handler)
Model Dropdown    → selectedModel güncelle (boş handler)
```

---

## Dosya Yapısı (Planlanan)

```
frontend/
├── UI_FLOW.md          ← bu dosya
├── refImages/
│   ├── image.png       ← Adım 1 → 2 geçişi
│   ├── image2.png      ← 1/3 ve 2/3 durumları
│   └── image3.png      ← 3/3 dolu durum
└── index.html          ← (yapılacak) tek HTML dosyası
```
