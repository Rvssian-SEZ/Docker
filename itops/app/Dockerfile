FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install internal CA cert if provided (for self-signed PKI like Step-CA)
# To use: copy your root_ca.crt into app/ before building
RUN if [ -s /app/root_ca.crt ]; then \
      cp /app/root_ca.crt /usr/local/share/ca-certificates/root_ca.crt && \
      update-ca-certificates; \
    fi

CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
