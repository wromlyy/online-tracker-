FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production

# Node.js 20 через NodeSource
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates bash \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python-зависимости
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Node-зависимости (без dev)
COPY package.json ./
RUN npm install --omit=dev

# Код проекта
COPY . .
RUN chmod +x start.sh

CMD ["./start.sh"]
