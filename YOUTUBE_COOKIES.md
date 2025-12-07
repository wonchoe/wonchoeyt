# YouTube Bot Detection Fix Guide

## Проблема

YouTube посилив захист від ботів і вимагає cookies для підтвердження. Помилка:
```
ERROR: [youtube] Sign in to confirm you're not a bot
```

## Рішення

### Крок 1: Експортуйте YouTube cookies

**Метод 1: Через браузерне розширення (рекомендовано)**

1. Встановіть [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. Відкрийте youtube.com в браузері
3. Авторизуйтесь (якщо не авторизовані)
4. Клікніть на іконку розширення → Export cookies.txt
5. Збережіть файл як `/tmp/cookies.txt` (або додайте до існуючого)

**Метод 2: Через yt-dlp (автоматично)**

```bash
# З Chrome
yt-dlp --cookies-from-browser chrome --cookies /tmp/yt_cookies.txt https://www.youtube.com/watch?v=dQw4w9WgXcQ

# З Firefox
yt-dlp --cookies-from-browser firefox --cookies /tmp/yt_cookies.txt https://www.youtube.com/watch?v=dQw4w9WgXcQ

# Додайте до існуючого файлу
cat /tmp/yt_cookies.txt >> /tmp/cookies.txt
```

**Метод 3: Вручну через DevTools**

1. Відкрийте youtube.com та авторизуйтесь
2. F12 → Application → Cookies → https://www.youtube.com
3. Знайдіть та скопіюйте cookies:
   - `__Secure-1PSID` (найважливіше!)
   - `__Secure-1PAPISID`
   - `__Secure-3PSID`
   - `__Secure-3PAPISID`
   - `HSID`
   - `SSID`
   - `APISID`
   - `SAPISID`

4. Додайте в `/tmp/cookies.txt`:
```
.youtube.com    TRUE    /    TRUE    0    __Secure-1PSID    YOUR_VALUE
.youtube.com    TRUE    /    TRUE    0    __Secure-1PAPISID    YOUR_VALUE
# ... інші cookies
```

### Крок 2: Перевірте cookies

```bash
# Перевірте що cookies файл існує
ls -lh /tmp/cookies.txt

# Перевірте що є YouTube cookies
grep youtube /tmp/cookies.txt | head -5

# Тест завантаження
yt-dlp --cookies /tmp/cookies.txt https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

### Крок 3: Перезапустіть бота

**Docker:**
```bash
cd /mnt/laravel/youtube-audio-downloader
docker-compose down
docker-compose build
docker-compose up -d
```

**Локально:**
```bash
ps aux | grep "python.*app.py" | grep -v grep | awk '{print $2}' | xargs -r kill -9
cd /mnt/laravel/youtube-audio-downloader && venv/bin/python app.py
```

## Додаткові виправлення

Бот тепер використовує:
- ✅ `player_client: ["android", "web"]` - multiple fallback clients
- ✅ Cookies з `/tmp/cookies.txt`
- ✅ Node.js v20 для JavaScript execution

## Troubleshooting

### Помилка "No JavaScript runtime"
- Node.js не встановлений
- Якщо Docker - перебудуйте образ: `docker-compose build`

### Помилка "Sign in to confirm you're not a bot"
- Cookies відсутні або застарілі
- Експортуйте нові cookies
- Переконайтесь що `/tmp/cookies.txt` існує і містить YouTube cookies

### Помилка "HTTP Error 403: Forbidden"
- YouTube заблокував ваш IP
- Спробуйте:
  1. Оновити cookies
  2. Використати VPN
  3. Почекати кілька годин

### Деякі відео не завантажуються
- Перевірте що ви авторизовані в YouTube
- Приватні відео потребують авторизації
- Вікові обмеження - потрібен авторизований акаунт

## Важливі cookies для YouTube

**Обов'язкові:**
- `__Secure-1PSID` - основний session ID
- `__Secure-3PSID` - додатковий session
- `HSID`, `SSID`, `APISID`, `SAPISID` - API credentials

**Додаткові (рекомендовано):**
- `__Secure-1PAPISID`
- `__Secure-3PAPISID`
- `LOGIN_INFO`
- `PREF`

## Безпека

⚠️ Cookies дають повний доступ до вашого YouTube акаунту!
- Не діліться `/tmp/cookies.txt` ні з ким
- Регулярно оновлюйте cookies (раз на 1-2 місяці)
- Якщо змінили пароль Google - оновіть cookies

## Альтернативні рішення

Якщо cookies не працюють:

1. **Використайте інший YouTube акаунт**
   - Створіть новий Google акаунт
   - Експортуйте cookies з нього

2. **Спробуйте інший браузер**
   - Chrome/Firefox/Edge можуть мати різні cookies

3. **Очистіть кеш браузера**
   - Вийдіть з YouTube
   - Очистіть cookies і кеш
   - Увійдіть знову
   - Експортуйте нові cookies
