# HTTPS and reverse proxies

**Advanced · Optional for local use**

A reverse proxy accepts requests at your domain, handles HTTPS and forwards them to MakerVault. A certificate makes the browser's connection encrypted. DNS maps the domain to the address serving it.

This example uses **Nginx running on the same host**, with an already-issued certificate for `maker.example.com`. Replace the domain and certificate paths with your own. Certificate issuance/renewal depends on your DNS and hosting environment; use [Nginx's HTTPS documentation](https://nginx.org/en/docs/http/configuring_https_servers.html) and your certificate provider's current instructions.

## 1. Restrict and configure MakerVault

```dotenv
MAKERVAULT_BIND_ADDRESS=127.0.0.1
MAKERVAULT_PORT=8765
DJANGO_ALLOWED_HOSTS=maker.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://maker.example.com
DJANGO_SECURE_COOKIES=true
TRUST_PROXY_HEADERS=true
TRUST_X_FORWARDED_HOST=false
ALLAUTH_TRUSTED_PROXY_COUNT=1
DJANGO_SECURE_SSL_REDIRECT=false
DJANGO_HSTS_SECONDS=0
```

Apply with `sudo docker compose up -d`. Loopback binding prevents direct LAN access to the app port in this same-host topology. Do not enable trusted proxy headers while leaving an untrusted alternate route to the application.

## 2. Configure Nginx

```nginx
server {
    listen 80;
    server_name maker.example.com;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name maker.example.com;
    ssl_certificate /etc/letsencrypt/live/maker.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/maker.example.com/privkey.pem;
    client_max_body_size 64m;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

This single-proxy example overwrites forwarded headers rather than trusting values supplied by the client. The 64 MiB request limit is an example proxy policy, not a claim that every 64 MiB file fits after multipart overhead or other app limits.

Validate your configuration with `sudo nginx -t`, then reload Nginx using your host's service manager. Ensure the certificate renewal process also reloads Nginx after renewal.

## 3. Verify before tightening redirects

Open the HTTPS domain. Check the valid certificate, login, a form save, image loading, file upload/download and Account & Security. If you use OIDC, update its exact callback URL to the HTTPS domain.

After HTTPS and forwarded scheme handling work, set `DJANGO_SECURE_SSL_REDIRECT=true` and recreate the app container. Start HSTS only after deciding the hostname will remain reliably HTTPS-only; a long-lived HSTS setting can lock browsers into HTTPS after a mistake.

## Other proxy topologies

A containerised proxy cannot reach the host's loopback port using its own `127.0.0.1`. Put the proxy and application on a deliberately configured shared Docker network and use the application's service address/port 8000, or arrange another restricted host route. A proxy on another machine similarly needs a reachable private address and firewall restriction.

The trusted proxy count must reflect the actual trusted chain. Do not copy `1` when another CDN/proxy sits in front without analysing its header behaviour.

Always forward private file requests through MakerVault. Do not expose `/app/media` as an unauthenticated Nginx alias or static file share. A proxy does not turn MakerVault into a public anonymous download service.
