FROM python:3.12-slim-trixie

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgtk-3-0t64 libx11-xcb1 libasound2t64 libdbus-glib-1-2 \
      libxt6 libxcomposite1 libxdamage1 libxrandr2 libxfixes3 \
      libxcursor1 libxi6 libpango-1.0-0 libcairo2 libpangocairo-1.0-0 \
      libnss3 libxss1 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 \
      libdrm2 libgbm1 libxkbcommon0 fonts-liberation \
      xvfb ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m camoufox fetch

COPY server.py /app/server.py

EXPOSE 8765

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]
