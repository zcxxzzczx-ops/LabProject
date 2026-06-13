FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    gcc build-essential \
    libmariadb-dev libmariadb-dev-compat \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgtk-3-0 libx11-xcb1 libxcb-dri3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m playwright install chromium 2>/dev/null || true
RUN python -m playwright install-deps chromium 2>/dev/null || true
RUN crawl4ai-setup 2>/dev/null || true

COPY backend/src/  ./src/
COPY gs_data/      ./gs_data/
COPY domains.json  ./domains.json

EXPOSE 8003

ENV PYTHONPATH=/app/src

CMD ["sh", "-c", "python src/init_db.py && uvicorn src.server:app --host 0.0.0.0 --port 8003"]
