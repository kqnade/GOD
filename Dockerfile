FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    "discord.py==2.7.1" \
    "Janome==0.5.0" \
    "Pillow==11.3.0" \
    "qrcode==8.2"

COPY README.md ./
COPY src ./src
COPY corpus ./corpus
RUN pip install --no-cache-dir --no-deps .

RUN mkdir -p /app/data
VOLUME ["/app/data"]

CMD ["god-bot"]
