# Install MakerVault

**Goal:** run MakerVault on a Linux server and reach its sign-in page.

## 1. Install Docker and the basic tools

Follow Docker's official instructions for your installed distribution: [Debian](https://docs.docker.com/engine/install/debian/) or [Ubuntu](https://docs.docker.com/engine/install/ubuntu/). Choose Docker Engine with the **Compose plugin** and **Buildx plugin**. Use the instructions for your actual OS release; do not paste Ubuntu package-repository commands into Debian.

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

**Expected result:** Docker reports its client and server versions, Compose reports a version, and the test container prints a success message. Resolve failures here before continuing. This guide uses `sudo docker` so you do not need to change Linux group membership.

## 2. Download the application

```bash
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/gavrd7/MakerVault.git
cd MakerVault
```

For private repository access, use GitHub's [HTTPS authentication guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github). Your ordinary GitHub password is not a Git credential. Do not put a token in the clone URL or paste one into a support message. An existing SSH setup may also be used.

The `main` branch is the project's deployable branch. The current release is v0.9.0.2. Read the guide and changelog from the revision you install; broader clean-install and upgrade acceptance is part of v1 hardening.

## 3. Create your configuration

Before editing, read [Configure your .env file](environment.md) for an explanation of the entries, secret generation and what must change. Read [Choose your storage](storage.md) to decide between Docker-managed volumes and host folders. The steps below are the short route for a new installation using named volumes.

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

A server may show several addresses, including Docker addresses. Use the LAN address assigned by your router. The example below uses **192.168.1.50**; replace it with yours. A DHCP reservation on your router can keep it stable.

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

Leave the four `*_STORAGE` values at their defaults for named volumes. Leave `DJANGO_DEBUG=false`, the HTTPS-only settings off, `ALLOW_LOCAL_REGISTRATION=false`, and the optional initial administrator password blank. We will create the administrator interactively.

In nano, press **Ctrl+O**, **Enter**, then **Ctrl+X** to save and exit. Keep `.env` private and out of Git.

## 4. Build and start

```bash
sudo docker compose config --quiet
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 -f makervault
```

The first command validates the Compose configuration without printing its secrets. The build downloads dependencies and may take several minutes. Startup applies database changes, creates roles and starter catalogues, and creates the private-file encryption key in its separate persistent storage.

Press **Ctrl+C** to stop following logs; this does not stop MakerVault. Wait for the services to become healthy. A first-run external catalogue request may take time. Repeated errors or restarting containers need investigation in [Troubleshooting](../reference/troubleshooting.md).

## 5. Create the administrator

When the app is running:

```bash
sudo docker compose exec makervault python manage.py createsuperuser
```

Follow the username, email and password prompts. Choose a unique password of at least 12 characters. Password typing is hidden. Save the credentials in your password manager.

There is no universal default login. Creating a superuser makes the account a full application administrator.

## 6. Open MakerVault

On another device connected to the same trusted network, open:

```text
http://192.168.1.50:8765
```

Replace the IP with your server address. `localhost` on your phone means your phone, not your server. If you changed `MAKERVAULT_PORT`, use that port in the URL and trusted origins.

**Success check:** the sign-in page loads, your administrator account works, and the Dashboard appears. Continue with [First sign-in](first-sign-in.md).

## Stop, start and apply configuration changes

```bash
sudo docker compose stop
sudo docker compose start
```

These stop and restart existing containers. After changing `.env`, use this instead so Compose recreates affected containers with the new configuration:

```bash
sudo docker compose up -d
```

Do not use `docker compose down -v` as a troubleshooting step. The `-v` option removes Compose-managed named volumes and can destroy your database, files and encryption key.
