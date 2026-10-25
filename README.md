# Multi-Platform Media Downloader Bot

Telegram бот для завантаження медіа з YouTube, Instagram, Facebook та TikTok.

## Підтримувані платформи

✅ **YouTube** - audio (MP3 192kbps) + video (360p/480p/720p)  
✅ **Instagram** - пости, reels, IGTV, фото, карусель з фото  
✅ **Facebook** - відеопости та Watch  
✅ **TikTok** - відео (включно з короткими посиланнями)

## Особливості

- 🎯 Автоматичне визначення платформи
- 🎬 Вибір якості для YouTube (360p/480p/720p)
- 📦 Підтримка каруселів Instagram
- 📤 Custom Telegram Bot API (підтримка файлів до 2GB)
- 🍪 Автоматичне оновлення cookies кожні 4 години
- 🧹 Автоматичне очищення файлів після надсилання
- ⏱️ Progress bar з ETA
- 🔒 Single instance lock

## Cookie Management

Бот використовує єдиний файл cookies для всіх платформ.  
**📖 Детальні інструкції: [COOKIE_MANAGEMENT.md](COOKIE_MANAGEMENT.md)**

### Швидка настройка cookies

Перший раз (на локальному сервері з GUI):
```bash
cd /mnt/laravel/youtube-audio-downloader
source venv/bin/activate
python3 cookie_refresher.py --login
```

Відкриється браузер - залогінься на YouTube, Instagram, Facebook.  
Cookies автоматично збережуться та будуть оновлюватись кожні 4 години через Kubernetes CronJob.

## Deployment

### Kubernetes (Production)

```bash
# Build та push Docker image
cd /mnt/laravel/youtube-audio-downloader
docker build -t wonchoe/ytdl-bot:latest .
docker push wonchoe/ytdl-bot:latest

# Deploy (файли в wonchoeyt repo)
kubectl apply -f k8s/

# Restart deployment
kubectl rollout restart deployment/ytdl-bot -n wonchoeyoutubebot

# Перевірка
kubectl get pods -n wonchoeyoutubebot
kubectl logs -n wonchoeyoutubebot deployment/ytdl-bot --tail=50
```

### Automated Daily Updates

The primary update path is `.github/workflows/docker-build.yml`: it runs on pushes,
daily at 03:00 UTC, or manually. It tests the downloader, builds a fresh ARM64 image
with the latest stable `yt-dlp`, and updates the pinned image digest in
`wonchoe/k3s-cursor.style`. ArgoCD then deploys it.

If GitHub disables the scheduled workflow due to repository inactivity, re-enable
it and trigger an update:

```bash
gh workflow enable docker-build.yml --repo wonchoe/wonchoeyt
gh workflow run docker-build.yml --repo wonchoe/wonchoeyt
```

A local `systemd` timer is also available as an alternative, provided the production
host has Docker Hub credentials with permission to push `wonchoe/ytdl-bot`:

- it pulls `/home/ubuntu/wonchoeyt`
- checks the latest stable `yt-dlp` release on PyPI
- rebuilds and pushes a new ARM64 image only when source or `yt-dlp` changed
- updates the pinned digest in `wonchoe/k3s-cursor.style`
- triggers ArgoCD sync and verifies rollout
- cleans old local `wonchoe/ytdl-bot` images and stale build cache

Files for this flow:

- `scripts/ytdl-bot-auto-update.sh`
- `ops/systemd/ytdl-bot-auto-update.service`
- `ops/systemd/ytdl-bot-auto-update.timer`

Install on production:

```bash
cd /home/ubuntu/wonchoeyt
sudo install -m 0644 ops/systemd/ytdl-bot-auto-update.service /etc/systemd/system/ytdl-bot-auto-update.service
sudo install -m 0644 ops/systemd/ytdl-bot-auto-update.timer /etc/systemd/system/ytdl-bot-auto-update.timer
sudo systemctl daemon-reload
sudo systemctl enable --now ytdl-bot-auto-update.timer
sudo systemctl start ytdl-bot-auto-update.service
```

Use one daily update path at a time to avoid concurrent image and GitOps updates.

### Docker Compose (Local)

```bash
docker-compose up -d
docker-compose logs -f
```

## Структура проекту

```
/mnt/laravel/youtube-audio-downloader/
├── app.py                    # Main Telegram bot
├── cookie_refresher.py       # Cookie management (login + auto-refresh)
├── entrypoint.sh            # Docker entrypoint
├── Dockerfile               # Container definition
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables (TELEGRAM_BOT_TOKEN)
├── downloaders/             # Platform-specific downloaders
│   ├── youtube.py          # YouTube (yt-dlp with cookies)
│   ├── instagram.py        # Instagram (yt-dlp + instaloader + gallery-dl)
│   ├── facebook.py         # Facebook (yt-dlp with cookies)
│   └── tiktok.py           # TikTok (yt-dlp)
├── utils/                   # Helpers
│   ├── progress.py         # Progress bar
│   └── telegram_api.py     # Custom Telegram Bot API client
├── COOKIE_MANAGEMENT.md     # Cookie setup guide
└── README.md               # This file
```

## Troubleshooting

### YouTube: "Sign in to confirm you're not a bot"
→ Див. [COOKIE_MANAGEMENT.md](COOKIE_MANAGEMENT.md)

### Instagram: вхід через браузер після помилки звичайних завантажувачів

Бот спочатку використовує yt-dlp, gallery-dl та Instaloader. Якщо вони не змогли
завантажити допис або Reel, остання спроба виконується у Chromium через Playwright
зі збереженим входом. Медіа береться з даних **відкритої вебсторінки**, прив’язаних
до конкретного shortcode допису; рекомендації та прев’ю відео не завантажуються.
Окремі потоки відео та звуку об’єднуються через ffmpeg.

Профіль за замовчуванням: `/var/www/playwright-profile/instagram-downloads`.
Він знаходиться всередині вже змонтованого постійного каталогу Kubernetes,
зберігається після перезапуску pod і відокремлений від профілю cookie-refresher.
Браузерна сесія не експортується до cookie-файлів yt-dlp/gallery-dl/Instaloader.

**Вхід на production-сервері через браузер на своєму комп’ютері:**

Спочатку розгорніть новий образ з цими змінами: у старому образі ще немає
`instagram_browser.py` та програм для noVNC. Потім у першому терміналі:

```bash
kubectl exec -it -n wonchoeyoutubebot deployment/ytdl-bot -- python instagram_browser.py login --remote
```

У другому терміналі на своєму комп’ютері:

```bash
kubectl port-forward -n wonchoeyoutubebot deployment/ytdl-bot 6080:6080
```

Відкрийте `http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`.
У вікні Chromium увійдіть в Instagram, пройдіть 2FA та перевірки акаунта.
Переконайтесь, що потрібний допис відтворюється. **Залиште вікно відкритим**,
поверніться у перший термінал і натисніть Enter. Дочекайтесь повідомлення
«Вхід збережений». Після цього браузер і noVNC завершаться; port-forward у другому
терміналі можна зупинити через Ctrl+C. Перезапускати бота після входу не потрібно.

noVNC слухає лише loopback усередині контейнера й працює тільки на час входу.
Для нього не потрібні Kubernetes Service, Ingress чи відкриття зовнішніх портів.
Сам браузер працює на сервері бота, тому вхід і наступні завантаження йдуть з
того самого сервера. Один профіль одночасно відкриває лише один процес.

Перевірка профілю та окремого завантаження:

```bash
kubectl exec -it -n wonchoeyoutubebot deployment/ytdl-bot -- python instagram_browser.py status
kubectl exec -it -n wonchoeyoutubebot deployment/ytdl-bot -- python instagram_browser.py check 'https://www.instagram.com/reel/DcRNIyUxZCS/'
```

`status` показує факт збереження входу та прапорець призупинення; `check` робить
реальне завантаження без Telegram у новий каталог `downloads/instagram-browser-check-*`.
Ці тестові файли можна видалити після перевірки.

Якщо Instagram перенаправить на login/challenge/checkpoint або покаже попередження
про автоматизацію, браузерні спроби призупиняться до нового ручного входу.
Повторіть `login --remote`, завершіть перевірки у вікні й натисніть Enter.
Для приватних/вікових дописів акаунт має мати доступ до самого допису.

**Локальна перевірка у WSL з графічним інтерфейсом:**

```bash
cd /mnt/laravel/wonchoeyt-local
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python instagram_browser.py --profile "$PWD/.instagram-profile" login
.venv/bin/python instagram_browser.py --profile "$PWD/.instagram-profile" check 'https://www.instagram.com/reel/DcRNIyUxZCS/'
```

Щоб локальний бот використовував той самий профіль, задайте у `.env`:
`INSTAGRAM_BROWSER_PROFILE=/mnt/laravel/wonchoeyt-local/.instagram-profile`.
Локальний профіль і серверний — різні: для production входьте через server noVNC.

### Instagram: "This content isn't available to everyone", login redirect або timeout

Наявність cookies Instagram ще не означає, що бот увійшов в акаунт:
потрібен чинний cookie `sessionid`. Cookies `csrftoken`, `ig_did`, `mid` самі по собі
не дають доступу до дописів, які вимагають входу. Автоматичний refresher не може
увійти в Instagram замість користувача; він тепер попереджає про відсутність сесії.

Для браузерної спроби використайте описаний вище `instagram_browser.py login`.
Якщо окремо потрібна авторизація старих завантажувачів, можна увійти через
`cookie_refresher.py --login` у середовищі з GUI з профілем refresher або
експортувати cookies власного акаунта у форматі Netscape. Перевірте, що цей акаунт
відкриває потрібний допис. Збережіть файл на сервері бота, не додаючи його в Git чи логи.

За замовчуванням бот читає `/var/www/ytdl-cookies.txt`. Окремий файл можна вказати
через `INSTAGRAM_COOKIES_FILE` (шлях **усередині контейнера**, файл потрібно змонтувати).
Окремий файл зручно використовувати для ручного експорту: загальний cookie-refresher
його не перезаписує.

Порядок спроб: анонімний yt-dlp → yt-dlp із cookies → gallery-dl із cookies →
анонімний gallery-dl → Instaloader → **Chromium зі збереженим браузерним входом**.
Спроби зі звичайним cookie-файлом виконуються лише за наявності непростроченого
`sessionid` у цьому файлі. Вхід через `instagram_browser.py login` незалежний
від цього cookie-файлу і достатній для останньої браузерної спроби.
Повні причини збоїв зберігаються в логах, а Telegram показує зрозуміле повідомлення.

### Facebook downloads не працюють
→ Перевір cookies: `cat /var/www/ytdl-cookies.txt | grep facebook`

### CronJob не оновлює cookies
```bash
kubectl logs -n wonchoeyoutubebot -l job-name=cookie-refresher --tail=50
```

## Environment Variables

- `TELEGRAM_BOT_TOKEN` - Telegram Bot API token (required)
- `TELEGRAM_API_BASE_URL` - Custom Telegram Bot API base URL (defaults to `http://telegram-bot-api:8081/bot`)
- `TELEGRAM_API_FILE_URL` - Custom Telegram Bot API file URL (defaults to `http://telegram-bot-api:8081/file/bot`)
- `INSTAGRAM_COOKIES_FILE` - Optional Netscape cookie file for Instagram (defaults to `/var/www/ytdl-cookies.txt`)
- `INSTAGRAM_BROWSER_PROFILE` - Persistent Chromium profile for the final Instagram fallback (defaults to `/var/www/playwright-profile/instagram-downloads`)

## License

MIT
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
