# Install MakerVault

**Goal:** run MakerVault on a Linux server and reach its sign-in page.

Using Windows instead? Follow [Install MakerVault on Windows](windows.md) for Docker Desktop, Docker Desktop + WSL2 integration, or Docker Engine directly inside WSL2.

This chapter covers a native Linux Docker host. MakerVault also supports the same Compose stack on Windows through the separate Windows guide.

MakerVault uses the published **GitHub Container Registry (GHCR)** images and one `docker-compose.yml` file. No compilation or extra deployment overlays are required.

## 1. Install Docker and the basic tools

Follow Docker's official instructions for your installed distribution: [Debian](https://docs.docker.com/engine/install/debian/) or [Ubuntu](https://docs.docker.com/engine/install/ubuntu/). Choose Docker Engine with the **Compose plugin**. 

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

The repository contains one Compose file (`docker-compose.yml`), `.env.example`, and the application and slicer source. The normal installation uses the published container image rather than compiling that source.

The default image is:

```text
ghcr.io/gavrd7/makervault:latest
```

You can pin a specific release later with `MAKERVAULT_IMAGE` if you prefer not to follow `latest`.

### Optional setup helper

The main repository already includes `python3 scripts/generate_env_secrets.py`. It creates `.env` from the example if needed and generates only `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` when absent or placeholders, preserving user-defined settings and existing secrets. Use it when installing from a checkout that contains the script. For a new installation, the browser-based first-run administrator wizard is the recommended way to create the first administrator.

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
MAKERVAULT_IMAGE=ghcr.io/gavrd7/makervault:1.1.0
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

Startup applies database changes, prepares the required roles and creates the private-file encryption key in its separate persistent storage. Starter catalogue seeding and enrichment can continue in the background rather than blocking access to the web interface.

Press **Ctrl+C** to stop following logs; this does not stop MakerVault.

### MakerVault Slicer in its own container

The standard `docker compose up -d` starts four long-running containers: MakerVault, **`makervault-slicer`**, PostgreSQL and Redis. There are **no profiles, extra Compose files or local builds**. The application and slicer are downloaded from GHCR. Only MakerVault's web/camera ports are published; the slicer, database and Redis are accessible only on the Docker network.

Your private `.env` contains different, automatically generated worker and installer tokens. The slicer uses a verified GHCR image; individual OrcaSlicer, Creality Print and Bambu Studio engines are managed separately in MakerVault. The engine-store volume is initialised from the published image on first deployment.

When the `v1.7.0` release tag is published, the same GitHub Actions workflow builds and publishes both GHCR images, recording the combined slicer's immutable digest in the application image. The deployment uses `ghcr.io/gavrd7/makervault-slicer:1.7.0` automatically. Do not substitute the earlier `0.1.0` image, which lacks the combined worker/installer. See [MakerVault Slicer](../3d-printing/slicer.md) for engine setup and compatibility checks, and [storage options](storage.md) to place the slicer engine store and other persistent data on selected host disks.

## 5. Set up the first administrator

MakerVault provides a browser-based first-run setup wizard when no administrator exists. Leave `MAKERVAULT_ADMIN_PASSWORD` empty in `.env` to use it. Open MakerVault in your browser at the address shown below: the first-run wizard should appear automatically. On the Docker host, retrieve the required token:

```bash
sudo docker compose exec -u makervault makervault python manage.py first_run_token
```

The token expires after 30 minutes. Do not share it. Enter it in the wizard along with your chosen username, email address, password and matching password confirmation. See [First sign-in](first-sign-in.md#first-administrator-on-a-new-installation) for full details, including recovery if a password is mistyped.

If you deliberately want terminal-based setup instead, `sudo docker compose exec makervault python manage.py createsuperuser` remains available. There is no universal default login.

## 6. Open MakerVault

On another device connected to the same trusted network, open:

```text
http://192.168.1.50:8765
```

Replace the IP with your server address. If you changed `MAKERVAULT_PORT`, use that port in the URL and trusted origins.

**Success check:** the first-run wizard appears if no administrator exists; after setup, your administrator account can sign in and the Dashboard appears. Continue with [First sign-in](first-sign-in.md).

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

For a source-build deployment, set `MAKERVAULT_IMAGE=makervault-local:dev` and build the application using the same Compose file:

```bash
sudo docker compose build makervault
sudo docker compose up -d
```

Do not use `docker compose down -v` as a troubleshooting step. The `-v` option removes Compose-managed named volumes and can destroy your database, files and encryption key.
