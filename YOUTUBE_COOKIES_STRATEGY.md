# YouTube Cookies Strategy

## Проблема
YouTube (Google) агресивно блокує cookies при використанні з ботів:
- Cookies живуть **5-10 хвилин** максимум
- Прив'язка до device fingerprint (IP, User-Agent, TLS fingerprint)
- Детект автоматизації (yt-dlp, нестандартні клієнти)
- Short-lived tokens (SAPISID, HSID, SSID)
- IP-based throttling

## Реалізоване рішення

### Dual Strategy: Cookies Optional + Android Client

**Спроба 1: З cookies** (для приватних/age-restricted відео)
```python
opts = {
    "cookiefile": "/tmp/ytdl-cookies.txt",
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
        }
    }
}
```

**Спроба 2: Без cookies** (для публічних відео)
```python
opts = {
    # No cookiefile
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
        }
    }
}
```

### Чому це працює

1. **Android client обходить Sign in challenge** - YouTube дозволяє android клієнтам завантажувати без авторизації
2. **Fallback механізм** - якщо cookies застаріли, автоматично пробує без них
3. **Менше false positives** - не всі запити використовують cookies
4. **Простіше в підтримці** - не потрібно постійно оновлювати cookies

## Коли потрібні cookies

✅ **Потрібні:**
- Приватні відео (unlisted/private)
- Age-restricted контент (18+)
- Region-blocked відео
- Premium контент

❌ **Не потрібні:**
- Публічні відео
- Музика, кліпи
- Більшість YouTube контенту

## Альтернативні рішення (не реалізовано)

### A. Headless Chrome + антидетект
```bash
# Playwright/Puppeteer з Stealth plugin
# Завжди тримати браузер залогіненим
# Бот дістає cookies автоматично
```
**Мінуси:** Важко, багато ресурсів, складна підтримка

### B. OAuth TV API
```bash
# youtube.com/activate
# Отримуємо довгоживучий токен (тижні)
```
**Мінуси:** Складна реалізація, може порушувати ToS

### C. Cookies from browser automatically
```bash
yt-dlp --cookies-from-browser chrome
```
**Мінуси:** Працює тільки локально, не на сервері

## Рекомендації

1. **Не використовуйте cookies для 90% запитів** - публічні відео працюють без них
2. **Оновлюйте cookies тільки для спеціальних випадків** - age-restricted/private
3. **Моніторте помилки** - якщо багато "Sign in" помилок, оновіть cookies
4. **Використовуйте android client** - найстабільніший варіант

## Оновлення cookies (коли потрібно)

1. Відкрийте YouTube в браузері (де залогінені)
2. Встановіть extension "Get cookies.txt LOCALLY"
3. Експортуйте cookies
4. Замініть `/var/www/ytdl-cookies.txt` на хості
5. Рестартуйте pod: `kubectl rollout restart deployment/ytdl-bot`

**Частота оновлення:** Раз на тиждень або за потреби (коли бачите помилки)
