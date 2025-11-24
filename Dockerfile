FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./

ENV TELEGRAM_BOT_TOKEN="" DOWNLOAD_DIR=/app/downloads

RUN mkdir -p "$DOWNLOAD_DIR"

CMD ["python", "app.py"]