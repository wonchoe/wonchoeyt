FROM python:3.11-slim

WORKDIR /app

# 1. Встановлюємо базові утиліти та Node.js v20
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    nano \
    gnupg \
    phantomjs \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 2. Встановлюємо найновішу версію yt-dlp та залежності для JS execution
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -U "yt-dlp>=2024.12.06" && \
    pip install --no-cache-dir websockets brotli pycryptodomex
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 3. Копіюємо entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 4. Перевірка версій
RUN node -v && npm -v && yt-dlp --version

ENTRYPOINT ["/entrypoint.sh"]
