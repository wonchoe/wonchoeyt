FROM python:3.11-slim

# Install ffmpeg for yt-dlp
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App file
COPY app.py .

# IMPORTANT:
# 1. cookies.txt буде змонтований Kubernetes у /app/cookies.txt (read-only)
# 2. Ми копіюємо його в /tmp/cookies.txt (rw)
# 3. Python запускається вже з правильним cookiefile
ENTRYPOINT ["sh", "-c", "cp /app/cookies.txt /tmp/cookies.txt 2>/dev/null || true && python3 /app/app.py"]
