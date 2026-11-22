# ClipForge public beta: Python/FFmpeg plus a supported JavaScript runtime for yt-dlp.
# Node.js 22 is required by yt-dlp's JavaScript challenge solver.
FROM node:22-bookworm-slim AS node_runtime
FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu-core ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
COPY static ./static
COPY assets ./assets
RUN mkdir -p media data
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
