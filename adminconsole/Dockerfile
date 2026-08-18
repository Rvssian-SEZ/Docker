FROM python:3.12-slim

ARG APP_VERSION=dev
ENV PYTHONUNBUFFERED=1 APP_VERSION=${APP_VERSION}

WORKDIR /app

# ldap3 pulls in no C deps of its own, but build-essential covers any
# wheel that needs compiling on an image without prebuilt manylinux wheels.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# App DB + separate append-only audit DB (host: /opt/appdata/adminconsole/data)
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
