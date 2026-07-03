FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY root_ca.crt /usr/local/share/ca-certificates/root_ca.crt
RUN update-ca-certificates

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run Alembic migrations then start the app
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
