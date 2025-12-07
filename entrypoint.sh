#!/bin/bash
set -e

# Копіюємо read-only cookies в /tmp/ якщо вони існують
if [ -f "/app/cookies.txt" ]; then
    echo "📋 Copying cookies from /app/cookies.txt to /tmp/cookies.txt..."
    cp /app/cookies.txt /tmp/cookies.txt
    chmod 644 /tmp/cookies.txt
    echo "✅ Cookies copied successfully"
else
    echo "⚠️  Warning: /app/cookies.txt not found, bot will work without cookies"
    echo "   Some platforms may have limitations without authentication"
fi

# Запускаємо основний процес
echo "🚀 Starting YouTube Downloader Bot..."
exec python app.py
