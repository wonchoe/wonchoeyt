FROM python:3.11-slim

WORKDIR /app

# ✅ Встановити Node.js (для yt-dlp JS runtime)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    nodejs \
    npm \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ✅ Встановити yt-dlp через pip (найновіша версія)
RUN pip install --no-cache-dir -U yt-dlp

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ✅ Перевірка чи Node.js встановлено
RUN node --version && npm --version

CMD ["python", "app.py"]
