# Deployment Guide

## HTTPS is mandatory

This API transmits an API key, card numbers, and identity-document data
in request and response bodies. **It must only be served behind TLS in any
environment reachable outside `localhost`.** Running it over plain HTTP on
a public network sends credentials and sensitive data in the clear.

Do **not** add `ssl_context` to the `uvicorn` command — TLS termination
is the job of a reverse proxy in front of the application.

## Reverse-proxy examples

### Caddy

```
yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy provisions a Let's Encrypt certificate automatically. Place this in
`/etc/caddy/Caddyfile` and restart Caddy.

### nginx

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Rate limiting

The application does not include built-in rate limiting. Apply per-IP rate
limits at the reverse-proxy layer to protect the Groq/OCR-backed endpoints
(`/api/analyze`, `/api/analyze/upload`, `/api/classify`). The `/api/health`
endpoint should remain unrestricted for uptime monitoring.

Example nginx configuration:

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;

server {
    # ... (TLS block from above)

    location /api/analyze {
        limit_req zone=api burst=5 nodelay;
        proxy_pass http://127.0.0.1:8000;
    }
    location /api/analyze/upload {
        limit_req zone=api burst=5 nodelay;
        client_max_body_size 10m;
        proxy_pass http://127.0.0.1:8000;
    }
    location /api/classify {
        limit_req zone=api burst=5 nodelay;
        proxy_pass http://127.0.0.1:8000;
    }
    location /api/health {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

## Environment variables

Copy `.env.example` to `.env` and fill in the required values:

| Variable        | Required | Description |
|----------------|----------|-------------|
| `API_KEY`      | Yes      | Shared secret for authenticating API requests. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `GROQ_API_KEY` | No       | If you want Groq-powered explanations and classification boosts. |
| `ALLOWED_ORIGINS` | No    | Comma-separated list of CORS origins (e.g. `https://yourapp.com`). If empty, no cross-origin requests are allowed. |

**`ENVIRONMENT=production` is mandatory for any real deployment.** Without it, `/docs`/`/redoc` stay exposed and the `X-API-Key` check is skipped entirely for every request — the app fails open, not closed. The server logs a warning at startup whenever it is not running in production mode; treat that warning as a deploy blocker.

The `.env` file is git-ignored. Never commit it to version control.
