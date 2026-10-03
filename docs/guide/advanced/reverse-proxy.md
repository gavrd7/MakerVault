# HTTPS and reverse proxies

## HTTPS certificate wizard

Superusers can open **Settings → HTTPS & certificates** to see the current browser host, native HTTPS status and certificate details.

The wizard presents three deployment paths:

- **Reverse proxy** — recommended for public/domain deployments. Your proxy manages its own publicly trusted ACME/Let's Encrypt certificate and forwards to MakerVault's ordinary HTTP port.
- **Public ACME / Let's Encrypt** — MakerVault explains the public challenge requirements. MakerVault deliberately does not give its web process host/Docker privileges to open public ports or manipulate DNS, so use the reverse proxy or another host-level ACME client when public validation is required.
- **MakerVault Local CA** — designed for private LAN addresses such as `192.168.x.x`. Enter the IP/DNS names, select **Generate local HTTPS certificate**, then download **MakerVault Local CA** and trust that public CA certificate on each client. The CA private key never has a GUI download route.

With `MAKERVAULT_HTTPS_ENABLED=auto` (the default), the native HTTPS process waits until a valid certificate appears in key storage. Generating a local certificate from Settings therefore brings the separate HTTPS listener online without disabling the normal HTTP/reverse-proxy listener.

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


## Optional native HTTPS listener

MakerVault can also serve HTTPS directly on a separate port without adding another container. This is optional; a reverse proxy remains the recommended setup for a stable domain name, public certificate automation and normal ports 80/443.

For direct HTTPS on a trusted LAN, add for example:

```dotenv
MAKERVAULT_HTTPS_ENABLED=true
MAKERVAULT_HTTPS_BIND_ADDRESS=0.0.0.0
MAKERVAULT_HTTPS_PORT=8443
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50
DJANGO_CSRF_TRUSTED_ORIGINS=http://192.168.1.50:8765,https://192.168.1.50:8443
```

The normal HTTP listener remains available on `MAKERVAULT_PORT`, so a reverse proxy can still use it as its backend. Do not enable `DJANGO_SECURE_SSL_REDIRECT` merely because the separate native HTTPS port is enabled: Django's generic redirect does not know that HTTPS is on a different external port, and the HTTP listener may intentionally be serving a trusted reverse proxy.

### Use your own certificate

Put a PEM certificate and matching private key under `KEY_STORAGE/tls` as `cert.pem` and `key.pem`, or change the two in-container paths deliberately:

```dotenv
KEY_STORAGE=/mnt/Server/MakerVault/keys
MAKERVAULT_TLS_CERT_FILE=/app/keys/tls/cert.pem
MAKERVAULT_TLS_KEY_FILE=/app/keys/tls/key.pem
MAKERVAULT_HTTPS_SELF_SIGNED=false
```

The pair may be CA-issued or self-signed. MakerVault validates that both files are readable and match before starting the HTTPS listener.

### Generate a persistent self-signed certificate

For a local/test deployment, MakerVault can generate a certificate once and keep it under `KEY_STORAGE/tls`:

```dotenv
MAKERVAULT_HTTPS_ENABLED=true
MAKERVAULT_HTTPS_BIND_ADDRESS=0.0.0.0
MAKERVAULT_HTTPS_PORT=8443
MAKERVAULT_HTTPS_SELF_SIGNED=true
MAKERVAULT_HTTPS_SELF_SIGNED_NAMES=192.168.1.50,makervault.local
DJANGO_CSRF_TRUSTED_ORIGINS=https://192.168.1.50:8443
```

Open `https://192.168.1.50:8443` (substituting your address). A self-signed certificate is encrypted TLS, but browsers do not trust it automatically. Import/trust the certificate or its issuing CA on each client if you want to remove the browser warning. MakerVault deliberately does not disable browser certificate verification.

The generated certificate/key are persistent and are included in new managed `.mvbackup` bundles. Existing v2 recovery bundles remain supported; because they predate native TLS, restoring one does not erase key storage already present on the target.

If every browser-facing route is HTTPS, set `DJANGO_SECURE_COOKIES=true`. If you still intentionally use direct HTTP for interactive browser access, secure-only session cookies will prevent sign-in over that HTTP route.
