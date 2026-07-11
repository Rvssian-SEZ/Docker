# ITOps Portal — Deployment Guide

## Prerequisites
- Docker + Docker Compose installed
- Authentik instance running and accessible
- Your internal CA cert in PEM format (if Authentik uses self-signed/internal TLS)

---

## Step 1 — Create folder structure

    mkdir -p /opt/appdata/itops && cd /opt/appdata/itops

## Step 2 — Copy your CA cert (if using internal TLS)

    cp /path/to/your/root_ca.pem /opt/appdata/itops/root_ca.pem

Skip if Authentik uses a public certificate (Let's Encrypt etc.)

## Step 3 — Create docker-compose.yml

Use the docker-compose.yml from the repo:
https://github.com/Rvssian-SEZ/Docker/blob/main/itops/docker-compose.yml

## Step 4 — Create .env

    POSTGRES_DB=itops
    POSTGRES_USER=itops
    POSTGRES_PASSWORD=changeme
    SECRET_KEY=generate_with_python3_-c_import_secrets_print_secrets.token_hex_32
    APP_BASE_URL=http://your-host-ip:8000
    APP_PORT=8000
    AUTHENTIK_BASE_URL=https://auth.yourdomain.com
    AUTHENTIK_SLUG=itops
    AUTHENTIK_CLIENT_ID=your_client_id
    AUTHENTIK_CLIENT_SECRET=your_client_secret
    PGADMIN_EMAIL=admin@yourdomain.com
    PGADMIN_PASSWORD=changeme
    PGADMIN_PORT=5050

## Step 5 — Internal CA cert (uncomment in .env if needed)

If Authentik uses self-signed or internal TLS, add these to .env:

    CA_CERT_PATH=/opt/appdata/itops/root_ca.pem
    REQUESTS_CA_BUNDLE=/opt/appdata/itops/root_ca.pem
    SSL_CERT_FILE=/opt/appdata/itops/root_ca.pem

Without this, token exchange fails with CERTIFICATE_VERIFY_FAILED.
Full down/up required after adding volume mounts (not just restart).

## Step 6 — Start

    cd /opt/appdata/itops && docker compose up -d
    docker compose logs app -f

Expected:
    Running upgrade  -> cf96b241efbe, init
    Running upgrade cf96b241efbe -> f670b392b67a, add contracts v2
    Running upgrade f670b392b67a -> ecabc5be4af0, add printers table
    Application startup complete.

## Step 7 — Authentik setup

1. Providers > New > OAuth2/OpenID Provider
   - Client type: Confidential
   - Redirect URI: http://your-host-ip:8000/auth/callback
   - Scopes: openid, profile, email
   - Copy Client ID and Secret into .env

2. Applications > New
   - Slug: itops
   - Provider: select above

3. Restart after updating .env:
    docker compose restart app

## Step 8 — Behind a reverse proxy

Update .env:
    APP_BASE_URL=https://itops.yourdomain.com

Update Authentik redirect URI to match, then restart app.

## Updating

    docker compose down && docker rmi ghcr.io/rvssian-sez/itops:latest && docker compose pull && docker compose up -d

## Troubleshooting

SSL: CERTIFICATE_VERIFY_FAILED
  -> Set CA_CERT_PATH, REQUESTS_CA_BUNDLE, SSL_CERT_FILE in .env
  -> Do full down/up not just restart after adding cert

Token exchange failed
  -> Check Authentik redirect URI matches APP_BASE_URL/auth/callback exactly

App crash-looping
  -> docker compose logs app --tail 30

## Source
https://github.com/Rvssian-SEZ/Docker/tree/main/itops


---

## Authentik User Sync

The app can sync all Authentik users into the local DB automatically.
Users appear in the directory without needing to log in first.

### 1. Create an API token in Authentik

1. Admin > Directory > Tokens and App passwords
2. Create > Token
   - Identifier: itops-sync
   - User: your admin user
   - Intent: API Token
3. Copy the token key

### 2. Add to .env

    AUTHENTIK_API_TOKEN=your_token_here

### 3. Add to docker-compose.yml environment section

    AUTHENTIK_API_TOKEN: ${AUTHENTIK_API_TOKEN:-}

### 4. Restart

    docker compose down && docker compose up -d

### Sync behaviour

- Syncs automatically every hour in the background
- Manual sync button available on the Users page
- Syncs: username, email, full name, groups, is_active status
- Also maps Authentik LDAP attributes: phone, department, title (if populated)
- Locally edited fields are never overwritten if already set
