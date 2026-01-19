FROM python:3.11-slim

WORKDIR /app

# 1. Встановлюємо базові утиліти, Node.js v20 та Playwright dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    nano \
    gnupg \
    # Playwright dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 2. Встановлюємо Python packages
RUN pip install --no-cache-dir -U pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Встановлюємо Playwright browsers
RUN playwright install chromium

COPY . .

# 4. Копіюємо entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 5. Перевірка версій
RUN node -v && npm -v && yt-dlp --version && python -c "import playwright; print('✅ Playwright OK')"

ENTRYPOINT ["/entrypoint.sh"]
