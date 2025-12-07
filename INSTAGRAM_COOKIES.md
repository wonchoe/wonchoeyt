# Instagram Cookies Setup Guide

## Чому потрібні cookies для Instagram?

Instagram блокує завантаження фото без авторизації (повертає 401 Unauthorized). Cookies дозволяють боту завантажувати приватні та публічні фото від вашого імені.

## Як отримати Instagram cookies

### Метод 1: Використання браузерного розширення (найпростіше)

1. Встановіть розширення для експорту cookies:
   - **Chrome/Edge**: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   - **Firefox**: [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)

2. Відкрийте instagram.com в браузері
3. Авторизуйтесь у свій акаунт
4. Клікніть на іконку розширення
5. Експортуйте cookies в форматі Netscape
6. **Додайте** Instagram cookies в існуючий `/tmp/cookies.txt` (не заміняйте весь файл!)

### Метод 2: Використання yt-dlp для генерації cookies

```bash
# Згенеруйте cookies з браузера
yt-dlp --cookies-from-browser chrome --cookies /tmp/ig_cookies.txt https://www.instagram.com

# Додайте до існуючого файлу
cat /tmp/ig_cookies.txt >> /tmp/cookies.txt
```

### Метод 3: Ручне додавання через DevTools

1. Відкрийте instagram.com та авторизуйтесь
2. Натисніть F12 (відкрити DevTools)
3. Перейдіть на вкладку "Application" → "Cookies" → "https://www.instagram.com"
4. Знайдіть наступні важливі cookies:
   - `sessionid` - ваш session ID (найважливіше!)
   - `csrftoken` - CSRF token
   - `ds_user_id` - ваш user ID
   - `mid` - machine ID

5. Додайте їх в `/tmp/cookies.txt` у форматі:
```
# Netscape HTTP Cookie File
.instagram.com   TRUE    /       TRUE    0       sessionid    YOUR_SESSION_ID
.instagram.com   TRUE    /       TRUE    0       csrftoken    YOUR_CSRF_TOKEN
.instagram.com   TRUE    /       TRUE    0       ds_user_id   YOUR_USER_ID
.instagram.com   TRUE    /       TRUE    0       mid          YOUR_MACHINE_ID
```

## Поточний стан cookies

Перевірте що у вас вже є cookies для YouTube:

```bash
grep instagram /tmp/cookies.txt
```

Якщо нічого не знайдено - додайте Instagram cookies одним з методів вище.

## Перевірка cookies

Після додавання cookies перезапустіть бота:

```bash
# Якщо Docker
cd /mnt/laravel/youtube-audio-downloader
docker-compose restart

# Якщо локально
ps aux | grep "python.*app.py" | grep -v grep | awk '{print $2}' | xargs -r kill -9
cd /mnt/laravel/youtube-audio-downloader && venv/bin/python app.py
```

## Підтримувані формати Instagram URL

- Пости з фото: `https://www.instagram.com/p/ABC123/`
- Карусель (альбом): `https://www.instagram.com/p/ABC123/` (кілька фото)
- Reels: `https://www.instagram.com/reel/ABC123/`
- IGTV: `https://www.instagram.com/tv/ABC123/`

## Безпека

⚠️ **Важливо**: 
- Не діліться файлом cookies ні з ким
- Cookies дають доступ до вашого Instagram акаунту
- Регулярно оновлюйте cookies (раз на 1-2 місяці)
- Якщо змінили пароль Instagram - оновіть cookies

## Troubleshooting

### Помилка "401 Unauthorized"
- Cookies застарілі або відсутні
- Перевірте що ви авторизовані в Instagram
- Оновіть cookies

### Помилка "Login required"
- Відсутні cookies або sessionid
- Переконайтесь що файл `/tmp/cookies.txt` містить Instagram cookies

### Відео завантажуються, а фото ні
- yt-dlp працює без cookies для відео
- Для фото потрібні cookies - додайте їх
