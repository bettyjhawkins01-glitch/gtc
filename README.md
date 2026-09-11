# 🤖 Bot GetContact Telegram — Railway Ready

Bot Telegram cek nomor HP via GetContact.  
Login otomatis dengan **device fingerprint random** (mirip app Android asli).  
Data tersimpan di **PostgreSQL Railway** — tahan restart & redeploy.

---

## 📁 Struktur File

```
getcontact-bot/
├── bot.py            → Bot utama
├── gtc_auth.py       → Login GTC (device random + OTP)
├── config.py         → Baca ENV variables
├── db.py             → PostgreSQL (user limit + session GTC)
├── Procfile          → Perintah start untuk Railway
├── railway.toml      → Konfigurasi Railway
├── requirements.txt  → Dependencies Python
├── .env.example      → Contoh ENV untuk lokal
└── README.md
```

---

## 🚀 Deploy ke Railway

### Step 1 — Upload ke GitHub
Push semua file ini ke repo GitHub (public atau private).

### Step 2 — Buat project di Railway
1. Buka [railway.app](https://railway.app) → New Project
2. Pilih **Deploy from GitHub repo**
3. Pilih repo kamu

### Step 3 — Tambah PostgreSQL
Di project Railway:
1. Klik **+ New** → **Database** → **PostgreSQL**
2. Railway otomatis set `DATABASE_URL` sebagai environment variable

### Step 4 — Set Environment Variables
Buka tab **Variables** di service bot kamu, tambahkan:

| Variable | Value |
|----------|-------|
| `BOT_TOKEN` | Token dari @BotFather |
| `GTC_PHONE` | Nomor HP akun GetContact (contoh: `628123456789`) |
| `LIMIT_PER_USER` | `3` |

> ⚠️ `DATABASE_URL` **tidak perlu diisi manual** — Railway otomatis inject dari plugin PostgreSQL.

### Step 5 — Deploy
Railway akan otomatis build & deploy. Lihat log di tab **Deployments**.

---

## 🔐 Flow Login di Bot

Setelah bot online, ketik di Telegram:

```
/login
```

```
Bot: ✅ Device di-generate! (Redmi 220333QNY, Android 12)
     📤 OTP dikirim ke +628xxxxxxxxx...

Kamu ketik kode OTP dari SMS → Bot login & simpan session ke PostgreSQL
```

Session tersimpan permanen di database — tidak perlu login ulang meski Railway restart.

---

## 📋 Commands

| Command | Fungsi |
|---------|--------|
| `/start` | Menu utama |
| `/login` | Login GTC (generate device + OTP) |
| `/logout` | Hapus session |
| `/status` | Info device & token aktif |
| `/cek` | Sisa kuota pencarian |
| `/cancel` | Batalkan proses login |

---

## 💻 Jalankan Lokal (Development)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Buat file .env dari contoh
cp .env.example .env
# → isi BOT_TOKEN, GTC_PHONE, DATABASE_URL

# 3. Load .env & jalankan
export $(cat .env | xargs) && python bot.py
```

---

## ⚡ Limit Pencarian

- Default: **3x per user Telegram** (permanen, tidak reset)
- Ubah via env variable `LIMIT_PER_USER`
- Data tersimpan di tabel `user_usage` PostgreSQL
