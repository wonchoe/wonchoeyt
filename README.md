# Multi-Platform Media Downloader Bot

Telegram бот для завантаження медіа з різних платформ.

## Підтримувані платформи

✅ **YouTube** - audio (MP3 192kbps) + video (360p/480p/720p)  
✅ **Instagram** - пости, reels, IGTV, фото, карусель з фото  
✅ **TikTok** - відео (включно з короткими посиланнями)  
⚠️ **Facebook** - звичайні відеопости, Watch (❌ НЕ Reels)

## Швидкий старт

### Cookies (ОБОВ'ЯЗКОВО!)

Для коректної роботи потрібні cookies від YouTube та Instagram:

```bash
# Експортуйте cookies через браузерне розширення або yt-dlp
yt-dlp --cookies-from-browser chrome --cookies /tmp/cookies.txt https://www.youtube.com

# Або додайте вручну в /tmp/cookies.txt
```

📖 Детальні інструкції:
- [YOUTUBE_COOKIES.md](YOUTUBE_COOKIES.md) - як виправити "Sign in to confirm you're not a bot"
- [INSTAGRAM_COOKIES.md](INSTAGRAM_COOKIES.md) - для завантаження фото
- [FACEBOOK_COOKIES.md](FACEBOOK_COOKIES.md) - для Facebook відео

### Docker (рекомендовано)

```bash
cd /mnt/laravel/youtube-audio-downloader

# Створіть .env файл
echo "TELEGRAM_BOT_TOKEN=your_token_here" > .env

# Додайте cookies
yt-dlp --cookies-from-browser chrome --cookies /tmp/cookies.txt https://www.youtube.com

# Запустіть
docker-compose up -d

# Логи
docker-compose logs -f
```

### Локально

```bash
cd /mnt/laravel/youtube-audio-downloader

# Створіть virtual environment
python3 -m venv venv
source venv/bin/activate

# Встановіть залежності
pip install -r requirements.txt

# Створіть .env
echo "TELEGRAM_BOT_TOKEN=your_token_here" > .env

# Додайте cookies
yt-dlp --cookies-from-browser chrome --cookies /tmp/cookies.txt https://www.youtube.com

# Запустіть
python app.py
```

## Можливості

- 🎯 Автоматичне визначення платформи
- 🎬 Вибір якості для YouTube (360p/480p/720p)
- 📦 Підтримка каруселів Instagram
- 📤 Автоматичне завантаження великих файлів (>50MB) на gofile.io
- 🍪 Підтримка cookies для bypassing rate limits
- 🧹 Автоматичне очищення файлів після надсилання
- ⏱️ Progress bar з ETA
- 🔒 Single instance lock

## Troubleshooting

### YouTube: "Sign in to confirm you're not a bot"
```bash
# Експортуйте cookies
yt-dlp --cookies-from-browser chrome --cookies /tmp/cookies.txt https://www.youtube.com

# Перезапустіть бота
docker-compose restart
```

### Instagram: "401 Unauthorized" для фото
```bash
# Додайте Instagram cookies
yt-dlp --cookies-from-browser chrome --cookies /tmp/ig_cookies.txt https://www.instagram.com
cat /tmp/ig_cookies.txt >> /tmp/cookies.txt
```

### Timeout помилки при великих файлах
- Вже виправлено - бот автоматично використовує gofile.io для файлів >50MB
- Збільшені timeouts до 120 секунд

## Структура проекту

```
youtube-audio-downloader/
├── app.py                      # Основний бот
├── downloaders/
│   ├── __init__.py
│   ├── base.py                # Базовий клас
│   ├── youtube.py             # YouTube downloader
│   ├── instagram.py           # Instagram downloader
│   ├── facebook.py            # Facebook downloader
│   └── tiktok.py              # TikTok downloader
├── utils/
│   ├── cleanup.py             # Автоочищення
│   └── upload.py              # Upload на gofile.io
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Ліцензія

MIT
