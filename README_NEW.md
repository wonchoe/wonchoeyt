# Multi-Platform Media Downloader Bot

Telegram бот для завантаження медіа з різних платформ.

## Підтримувані платформи

- ✅ **YouTube** - відео, музика, shorts
- ✅ **Instagram** - пости, reels, IGTV, carousel

## Структура проекту

```
youtube-audio-downloader/
├── app.py                 # Старий бот (тільки YouTube)
├── app_new.py            # Новий модульний бот
├── downloaders/          # Модулі завантажувачів
│   ├── __init__.py
│   ├── base.py          # Базовий клас
│   ├── youtube.py       # YouTube downloader
│   └── instagram.py     # Instagram downloader
├── utils/               # Утиліти
│   ├── __init__.py
│   ├── cleanup.py       # Очищення файлів
│   └── upload.py        # Завантаження великих файлів
└── downloads/           # Тимчасові файли
```

## Встановлення

1. Віртуальне оточення вже створене:
```bash
source venv/bin/activate
```

2. Перемикання на новий бот:
```bash
# Зупинити старий бот
ps aux | grep "python.*app.py" | awk '{print $2}' | xargs -r kill -9
rm -f /tmp/ytdlbot.lock

# Запустити новий
python app_new.py
```

## Використання

### Через Telegram бот

1. Надішліть посилання боту
2. Для YouTube - виберіть Audio/Video
3. Для Instagram - автоматично завантажить

### Тестовий режим (command line)

YouTube:
```bash
python app_new.py https://youtube.com/watch?v=... audio
python app_new.py https://youtube.com/watch?v=... video 720
```

Instagram:
```bash
python app_new.py https://instagram.com/p/...
```

## Додавання нових платформ

### 1. Створити новий downloader

```python
# downloaders/tiktok.py
from .base import BaseDownloader

class TikTokDownloader(BaseDownloader):
    PATTERNS = [r'tiktok\.com']
    
    @staticmethod
    def can_handle(url: str) -> bool:
        return 'tiktok.com' in url
    
    async def download(self, url, download_dir, progress_callback=None):
        # Ваша логіка завантаження
        pass
```

### 2. Зареєструвати в app_new.py

```python
from downloaders import TikTokDownloader

DOWNLOADERS = [
    YouTubeDownloader(),
    InstagramDownloader(),
    TikTokDownloader(),  # Додати тут
]
```

## Особливості

- 🔒 **Single instance lock** - тільки один екземпляр бота
- 🧹 **Auto cleanup** - видалення старих файлів (30 хвилин)
- 📤 **Large file upload** - великі файли на gofile.io
- 🍪 **Cookies support** - використання `/tmp/cookies.txt`
- 📊 **Progress tracking** - прогрес-бар завантаження

## Troubleshooting

### Instagram не завантажується

Instagram може вимагати авторизацію. Експортуйте cookies:

```bash
# Використовуйте browser extension для експорту cookies
# Збережіть в /tmp/cookies.txt у Netscape format
```

### Помилка "No module named 'downloaders'"

```bash
cd /mnt/laravel/youtube-audio-downloader
python app_new.py  # Запускайте з цієї теки
```

## Міграція зі старого бота

Старий `app.py` залишається для сумісності. Новий `app_new.py` - повністю модульний.

Щоб перейти:
1. Протестуйте `app_new.py`
2. Якщо все ОК, перейменуйте:
```bash
mv app.py app_old.py
mv app_new.py app.py
```
