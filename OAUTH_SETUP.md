# YouTube OAuth Setup Guide

## Проблема
YouTube агресивно блокує:
- ❌ Cookies (живуть 5-10 хвилин)
- ❌ Android/iOS/TV clients
- ❌ Всі стандартні методи обходу

## Рішення: OAuth TV API

YouTube TV використовує OAuth токени які:
- ✅ Живуть **тижнями/місяцями**
- ✅ Автоматично оновлюються
- ✅ Не прив'язані до IP/fingerprint
- ✅ Легальні та стабільні

## Крок 1: Налаштування OAuth (один раз)

### На локальній машині:

```bash
cd /mnt/laravel/youtube-audio-downloader
python3 oauth_helper.py setup
```

Отримаєте:
```
📱 Відкрийте у браузері: https://www.google.com/device
🔑 Введіть код: XXXX-YYYY
⏳ Чекаю активації...
```

### Активація:

1. Відкрийте https://www.google.com/device в браузері
2. Введіть код (XXXX-YYYY)
3. Виберіть Google акаунт (той де ви дивитесь YouTube)
4. Підтвердіть доступ

### Результат:

```
✅ OAuth setup completed!
📝 Access token: ya29.a0AfH6SMBz...
🔄 Refresh token: 1//0gYT1Z3...
⏰ Expires in: 3600s
```

Токен збережено у `/tmp/youtube_oauth_token.json`

## Крок 2: Копіювання токену в Kubernetes

### Спосіб A: Через Secret (рекомендовано)

```bash
# На локальній машині де створили токен
kubectl create secret generic youtube-oauth \
  --from-file=token=/tmp/youtube_oauth_token.json \
  -n default
```

Оновіть `dep.yaml`:
```yaml
volumeMounts:
  - name: oauth-token
    mountPath: /tmp/youtube_oauth_token.json
    subPath: token
    readOnly: true

volumes:
  - name: oauth-token
    secret:
      secretName: youtube-oauth
```

### Спосіб B: Через hostPath (простіше)

```bash
# Скопіювати на хост де працює K8s
scp /tmp/youtube_oauth_token.json user@k8s-host:/var/www/

# Оновити dep.yaml
volumes:
  - name: oauth-token
    hostPath:
      path: /var/www/youtube_oauth_token.json
      type: File
```

## Крок 3: Рестарт бота

```bash
kubectl rollout restart deployment/ytdl-bot
```

## Перевірка

Логи повинні показати:
```
🔐 YouTube OAuth token found
🔐 Using OAuth authentication (most reliable)
🔄 Attempting download OAuth (most reliable)...
✅ Downloaded successfully OAuth (most reliable)
```

## Оновлення токену

OAuth токени автоматично оновлюються через `refresh_token`.

Якщо потрібно оновити вручну:
```bash
python3 oauth_helper.py refresh
```

## Troubleshooting

### "No token found"
```bash
python3 oauth_helper.py setup  # Створити токен заново
```

### "Token expired"
Токен автоматично оновлюється. Якщо ні:
```bash
python3 oauth_helper.py setup  # Створити новий
```

### "Invalid grant"
Refresh token застарів (рідко, раз на місяці):
```bash
python3 oauth_helper.py setup  # Створити новий
```

## Порівняння методів

| Метод | Час життя | Стабільність | Складність |
|-------|-----------|--------------|------------|
| **OAuth** | Тижні/місяці | ⭐⭐⭐⭐⭐ | Легко |
| Cookies | 5-10 хвилин | ⭐ | Легко |
| Headless browser | Поки працює | ⭐⭐⭐ | Складно |

## Рекомендація

✅ **Використовуйте OAuth** для production
- Один раз налаштували - працює місяцями
- Автоматичне оновлення
- Найстабільніше рішення
