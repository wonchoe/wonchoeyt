#!/bin/bash
set -e

# Чіткі шляхи для cookies
HOSTPATH_COOKIES="/var/www/ytdl-cookies.txt"
TMP_COOKIES="/tmp/ytdl-cookies.txt"

echo "🔍 Checking for cookies sources..."

# Видаляємо старий /tmp/ytdl-cookies.txt якщо він застарілий
if [ -f "$TMP_COOKIES" ]; then
    echo "🗑️  Removing old $TMP_COOKIES..."
    rm -f "$TMP_COOKIES"
fi

# Копіюємо та конвертуємо cookies з /app/ytdl-cookies.txt (hostPath)
if [ -f "$HOSTPATH_COOKIES" ]; then
    echo "📋 Found cookies at $HOSTPATH_COOKIES"
    COOKIE_SIZE=$(stat -f%z "$HOSTPATH_COOKIES" 2>/dev/null || stat -c%s "$HOSTPATH_COOKIES" 2>/dev/null)
    echo "📦 Cookie file size: $COOKIE_SIZE bytes"
    
    if [ "$COOKIE_SIZE" -gt 100 ]; then
        echo "✅ Copying cookies to $TMP_COOKIES..."
        
        # Просто копіюємо файл без конвертації
        cp "$HOSTPATH_COOKIES" "$TMP_COOKIES"
        chmod 644 "$TMP_COOKIES"
        
        COOKIE_COUNT=$(grep -v '^#' "$TMP_COOKIES" | grep -v '^$' | wc -l)
        echo "✅ Cookies copied successfully: $COOKIE_COUNT cookies"
    else
        echo "⚠️  Warning: Cookie file is too small ($COOKIE_SIZE bytes), might be empty"
    fi
else
    echo "⚠️  Warning: /var/www/ytdl-cookies.txt not found"
    echo "   Bot will work without cookies - some platforms may have limitations"
    echo "   Ensure /var/www/ytdl-cookies.txt exists on host and is mounted correctly"
fi

# Показуємо фінальний стан cookies
if [ -f "$TMP_COOKIES" ]; then
    FINAL_SIZE=$(stat -f%z "$TMP_COOKIES" 2>/dev/null || stat -c%s "$TMP_COOKIES" 2>/dev/null)
    COOKIE_COUNT=$(grep -v '^#' "$TMP_COOKIES" | grep -v '^$' | wc -l)
    echo "📊 Final cookies status: $COOKIE_COUNT cookies, $FINAL_SIZE bytes"
else
    echo "❌ No cookies available - bot will run with limited functionality"
fi

# Перевірка Node.js для yt-dlp JavaScript challenges
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    NODE_PATH=$(which node)
    echo "✅ Node.js detected: $NODE_VERSION at $NODE_PATH"
    
    # Переконуємось що Node.js в PATH
    export PATH="/usr/bin:$PATH"
    
    # Тест JavaScript execution
    if node -e "console.log('JS OK')" &> /dev/null; then
        echo "✅ Node.js JavaScript execution works"
    else
        echo "⚠️  Node.js found but JS execution failed"
    fi
else
    echo "⚠️  Warning: Node.js not found - YouTube signature solving may fail"
fi

# Запускаємо основний процес
echo "🚀 Starting YouTube Downloader Bot..."
exec python app.py
