FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step-CA internal root cert — required for httpx to trust auth.home.internal
COPY root_ca.crt /usr/local/share/ca-certificates/home-internal.crt
RUN update-ca-certificates

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
