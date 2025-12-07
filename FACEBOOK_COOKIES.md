# Facebook Cookies Setup Guide

## Чому потрібні cookies?

Facebook блокує завантаження відео без авторизації. Cookies дозволяють боту завантажувати приватні та публічні відео від вашого імені.

## Як отримати Facebook cookies

### Метод 1: Використання браузерного розширення (найпростіше)

1. Встановіть розширення для експорту cookies:
   - **Chrome/Edge**: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   - **Firefox**: [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)

2. Відкрийте facebook.com в браузері
3. Авторизуйтесь у свій акаунт
4. Клікніть на іконку розширення
5. Експортуйте cookies в форматі Netscape
6. Скопіюйте вміст в `/tmp/cookies.txt`

### Метод 2: Ручне додавання через DevTools

1. Відкрийте facebook.com та авторізуйтесь
2. Натисніть F12 (відкрити DevTools)
3. Перейдіть на вкладку "Application" → "Cookies" → "https://www.facebook.com"
4. Знайдіть наступні важливі cookies:
   - `c_user` - ваш user ID
   - `xs` - session token
   - `datr` - device token
   - `sb` - security token

5. Додайте їх в `/tmp/cookies.txt` у форматі:
```
# Netscape HTTP Cookie File
.facebook.com   TRUE    /       TRUE    0       c_user  YOUR_USER_ID
.facebook.com   TRUE    /       TRUE    0       xs      YOUR_XS_TOKEN
.facebook.com   TRUE    /       TRUE    0       datr    YOUR_DATR_TOKEN
.facebook.com   TRUE    /       TRUE    0       sb      YOUR_SB_TOKEN
```

### Метод 3: Використання yt-dlp для генерації cookies

```bash
# Встановіть yt-dlp якщо ще не встановлено
pip install yt-dlp

# Згенеруйте cookies з браузера
yt-dlp --cookies-from-browser chrome --cookies /tmp/cookies.txt https://www.facebook.com
```

## Перевірка cookies

Після додавання cookies перезапустіть бота:

```bash
cd /mnt/laravel/youtube-audio-downloader
source venv/bin/activate
python app.py
```

## Підтримувані формати Facebook URL

- Пости: `https://www.facebook.com/username/posts/123456`
- Відео: `https://www.facebook.com/watch/?v=123456`
- Коротке посилання: `https://fb.watch/abc123`
- Stories: `https://www.facebook.com/stories/123456`
- Reels: `https://www.facebook.com/reel/123456`

## Безпека

⚠️ **Важливо**: 
- Не діліться файлом cookies ні з ким
- Cookies дають доступ до вашого Facebook акаунту
- Регулярно оновлюйте cookies (раз на 1-2 місяці)
- Якщо змінили пароль Facebook - оновіть cookies

## Troubleshooting

### Помилка "403 Forbidden"
- Cookies застарілі, потрібно оновити
- Перевірте що ви авторизовані в Facebook

### Помилка "Login required"
- Cookies відсутні або некоректні
- Перевірте формат файлу cookies.txt

### Помилка "This video is private"
- Відео доступне тільки для певних користувачів
- Переконайтесь що ваш акаунт має доступ до відео
