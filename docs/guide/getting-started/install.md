# Install MakerVault

**Goal:** run MakerVault on a Linux server and reach its sign-in page.

Using Windows instead? Follow [Install MakerVault on Windows](windows.md) for Docker Desktop, Docker Desktop + WSL2 integration, or Docker Engine directly inside WSL2.

This chapter covers a native Linux Docker host. MakerVault also supports the same Compose stack on Windows through the separate Windows guide.

MakerVault supports two image routes:

- **Recommended:** pull the pre-built image from GitHub Container Registry (GHCR). This is the simplest route and does not compile MakerVault on your server.
- **Build it yourself:** clone the same repository and build the Docker image locally from the supplied Dockerfile.

Both routes use the same Compose stack, `.env`, database and persistent storage.

## 1. Install Docker and the basic tools

Follow Docker's official instructions for your installed distribution: [Debian](https://docs.docker.com/engine/install/debian/) or [Ubuntu](https://docs.docker.com/engine/install/ubuntu/). Choose Docker Engine with the **Compose plugin**. The Buildx plugin is also required if you want to build MakerVault locally.

Install the remaining tools on Debian/Ubuntu:

```bash
sudo apt update
sudo apt install git python3 nano
```

Verify Docker:

```bash
sudo docker version
sudo docker compose version
sudo docker run --rm hello-world
```

**Expected result:** Docker reports its client and server versions, Compose reports a version, and the test container prints a success message.

## 2. Download the deployment files

Clone the public MakerVault repository:

```bash
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/gavrd7/MakerVault.git
cd MakerVault
```

The repository contains the Compose configuration, `.env.example`, the optional source-build override and the application source. The normal installation uses the published container image rather than compiling that source.

The default image is:

```text
ghcr.io/gavrd7/makervault:latest
```

You can pin a specific release later with `MAKERVAULT_IMAGE` if you prefer not to follow `latest`.

## 3. Create your configuration

Before editing, read [Configure your .env file](environment.md) for an explanation of the entries, secret generation and what must change. Read [Choose your storage](storage.md) to decide between Docker-managed volumes and host folders.

**Existing installation?** Keep your current `.env`; do not copy the example over it or regenerate its secrets. Use the [update guide](../administration/updates.md).

```bash
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Copy the generated random value. It is your **Django secret key**, not your login password or file-encryption key. Generate a second value for the database password by running the Python command again.

Find your server's network address:

```bash
hostname -I
```

A server may show several addresses, including Docker addresses. Use the LAN address assigned by your router. The example below uses **192.168.1.50**; replace it with yours.

```bash
nano .env
```

Edit the existing lines rather than adding duplicate entries:

| Setting | What to enter |
| --- | --- |
| `DJANGO_SECRET_KEY` | Your first generated random value |
| `POSTGRES_PASSWORD` | Your second generated random value |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,192.168.1.50` with your actual IP; no scheme or port |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `http://localhost:8765,http://192.168.1.50:8765` with your actual IP |
| `TRUST_PROXY_HEADERS` | `false` for this direct-access installation |
| `ALLAUTH_TRUSTED_PROXY_COUNT` | `0` |
| `TZ` and `DJANGO_TIME_ZONE` | Your timezone, for example `Europe/London` |
| `MAKERVAULT_CURRENCY` | Your currency code, for example `GBP` |

Leave the storage values at their defaults for named volumes. Leave `DJANGO_DEBUG=false`, the HTTPS-only settings off, `ALLOW_LOCAL_REGISTRATION=false`, and the optional initial administrator password blank.

To pin MakerVault to one published version, optionally add:

```dotenv
MAKERVAULT_IMAGE=ghcr.io/gavrd7/makervault:1.0.2
```

If that setting is omitted, Compose uses `ghcr.io/gavrd7/makervault:latest`.

## 4. Pull and start MakerVault (recommended)

Validate the Compose configuration, pull the published images and start the stack:

```bash
sudo docker compose config --quiet
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 -f makervault
```

The MakerVault application image is downloaded from GHCR; PostgreSQL and Redis are pulled from their upstream registries. The server does **not** build the MakerVault application in this route.

Startup applies database changes, creates roles and starter catalogues, and creates the private-file encryption key in its separate persistent storage.

Press **Ctrl+C** to stop following logs; this does not stop MakerVault.

### Build MakerVault yourself instead

If you do not want to use the pre-built GHCR image, use the optional source-build override:

```bash
sudo docker compose -f compose.yaml -f compose.build.yaml config --quiet
sudo docker compose -f compose.yaml -f compose.build.yaml up -d --build
sudo docker compose -f compose.yaml -f compose.build.yaml ps
```

This builds the checked-out source using the repository Dockerfile and tags the local application image as `makervault-local:dev`.

The source-build route changes only how the MakerVault application image is obtained. It uses the **same** PostgreSQL database, Redis data, media, encryption keys, backups, ports and `.env` settings as the GHCR route.

## 5. Create the administrator

When the app is running:

```bash
sudo docker compose exec makervault python manage.py createsuperuser
```

Follow the username, email and password prompts. Choose a unique password of at least 12 characters. Password typing is hidden.

There is no universal default login.

## 6. Open MakerVault

On another device connected to the same trusted network, open:

```text
http://192.168.1.50:8765
```

Replace the IP with your server address. If you changed `MAKERVAULT_PORT`, use that port in the URL and trusted origins.

**Success check:** the sign-in page loads, your administrator account works, and the Dashboard appears. Continue with [First sign-in](first-sign-in.md).

## Stop, start and apply configuration changes

For the normal GHCR installation:

```bash
sudo docker compose stop
sudo docker compose start
```

After changing `.env`, use:

```bash
sudo docker compose up -d
```

For a source-build deployment, include the override file whenever you need Compose to recreate or rebuild the application from source:

```bash
sudo docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

Do not use `docker compose down -v` as a troubleshooting step. The `-v` option removes Compose-managed named volumes and can destroy your database, files and encryption key.
