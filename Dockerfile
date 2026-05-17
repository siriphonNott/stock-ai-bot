FROM python:3.11-slim

WORKDIR /app

# System deps for Pillow (libjpeg, zlib are already in the slim image's libc but be explicit)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# -u for unbuffered output so logs stream to Railway live
CMD ["python", "-u", "bot.py"]
