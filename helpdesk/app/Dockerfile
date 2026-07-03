FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY root_ca.crt /usr/local/share/ca-certificates/home-internal.crt
COPY requirements.txt .
RUN update-ca-certificates && pip install --no-cache-dir -r requirements.txt

COPY . .

# Create uploads dir
RUN mkdir -p /app/uploads

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
