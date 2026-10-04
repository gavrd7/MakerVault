# Install MakerVault on Windows

**Goal:** run MakerVault on a Windows PC using Docker Desktop or WSL2.

MakerVault's containers are Linux containers, so Windows needs a Linux-capable Docker environment. There are three practical ways to provide it:

| Method | Best for | Recommendation |
| --- | --- | --- |
| Docker Desktop from Windows Terminal / PowerShell | Most Windows users | **Easiest Windows route** |
| Docker Desktop with WSL2 integration | Users who prefer Linux commands while keeping Docker Desktop | **Recommended if you already use WSL** |
| Docker Engine installed directly inside a WSL2 distribution | Experienced users who deliberately want WSL to behave like a Linux server | Supported deployment pattern, but more administration is yours |

A dedicated Debian or Ubuntu host remains the simplest choice for an always-on appliance-style server, but you do **not** need a separate Linux computer to use MakerVault.

## Before you start

You need:

- a supported Windows version with hardware virtualisation enabled;
- WSL2 for the normal Docker Desktop backend;
- Git;
- enough disk space for MakerVault, PostgreSQL, uploaded models/files, container images and backups.

Microsoft's current WSL installation command, from an Administrator PowerShell or Windows Terminal, is:

```powershell
wsl --install
```

Restart Windows if requested, then keep WSL current:

```powershell
wsl --update
wsl --status
```

Docker Desktop's WSL2 backend is the normal choice for most Windows systems. Install Docker Desktop from Docker's official Windows installer and use **Linux containers**.

!!! note "Docker Desktop licensing"
    Docker Desktop is free for personal use, education, non-commercial open-source projects and qualifying small businesses. Larger commercial organisations should check Docker's current subscription terms.

## Option A: Docker Desktop from Windows Terminal or PowerShell

This is the least complicated Windows installation.

### 1. Install and verify Docker Desktop

Start Docker Desktop and wait until Docker reports that the engine is running.

Open **PowerShell** or **Windows Terminal**:

```powershell
docker version
docker compose version
docker run --rm hello-world
```

All three commands should succeed.

### 2. Clone MakerVault

Choose a normal local folder. For example:

```powershell
mkdir C:\MakerVault
cd C:\
git clone https://github.com/gavrd7/MakerVault.git MakerVault
cd C:\MakerVault
```

You can use another location under your user profile if you prefer.

### 3. Create the .env file

In PowerShell:

```powershell
Copy-Item .env.example .env
```

Generate a Django secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Run the command a second time for a separate PostgreSQL password.

If Python is not installed on Windows, PowerShell can generate strong random values instead:

```powershell
[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(64))
```

Edit `.env` in your preferred text editor. For access from the same PC, include at least:

```dotenv
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8765
TRUST_PROXY_HEADERS=false
ALLAUTH_TRUSTED_PROXY_COUNT=0
```

If other devices on your LAN will use MakerVault, also add the **Windows host's LAN address** to the allowed hosts and trusted origins.

For a first Windows installation, keep the supplied **Docker named-volume** storage values. They avoid Windows/Linux path and permission differences.

### 4. Start MakerVault

Docker Desktop does not normally require `sudo`:

```powershell
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 -f makervault
```

Press **Ctrl+C** to stop following the log; MakerVault keeps running.

Create the first administrator:

```powershell
docker compose exec makervault python manage.py createsuperuser
```

Then open:

```text
http://localhost:8765
```

For another device on your network, use the Windows PC's LAN address instead, for example `http://192.168.1.50:8765`.

### 5. Starting after a Windows reboot

MakerVault containers use Docker restart policies, but Docker Desktop itself must be running. If this PC is intended to behave like an always-on server, enable Docker Desktop's Windows sign-in/startup option and confirm MakerVault returns after a reboot.

A Windows PC that is routinely shut down, put to sleep or signed out is naturally less suitable as a continuously available household server than an always-on Linux host.

---

## Option B: Docker Desktop with WSL2 integration

This uses Docker Desktop's engine but lets you administer MakerVault from an Ubuntu/Debian WSL terminal.

This is a particularly good choice if you are comfortable with Linux commands because the MakerVault instructions remain very close to the main Linux guide.

### 1. Enable WSL integration

In Docker Desktop, enable the WSL2 engine and enable integration for the Linux distribution you want to use.

From Windows, confirm your distribution is using WSL2:

```powershell
wsl -l -v
```

If required:

```powershell
wsl --set-version Ubuntu 2
```

Substitute your actual distribution name.

Open the WSL distribution and verify:

```bash
docker version
docker compose version
docker run --rm hello-world
```

!!! important "Do not install a second Docker Engine unnecessarily"
    If you are using Docker Desktop's WSL integration, the Docker CLI inside WSL should talk to Docker Desktop. Do not also install and run an independent Docker daemon inside the same distribution unless you deliberately intend to manage two separate Docker environments.

### 2. Keep the MakerVault checkout in the Linux filesystem

For better Linux filesystem behaviour, keep the repository under the WSL distribution, for example:

```bash
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/gavrd7/MakerVault.git
cd MakerVault
```

Prefer this over placing the active checkout under `/mnt/c/...` when using the WSL workflow.

Windows can still browse these files through WSL's filesystem integration.

### 3. Configure and start

From the WSL terminal:

```bash
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Generate a second value for `POSTGRES_PASSWORD`, edit `.env`, then:

```bash
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
docker compose exec makervault python manage.py createsuperuser
```

Notice that these commands do **not** use `sudo` when the Docker CLI is connected to Docker Desktop.

On the same Windows PC, open:

```text
http://localhost:8765
```

For LAN access, use the Windows host's LAN address and include that address in `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.

---

## Option C: Docker Engine directly inside WSL2

You can also treat a WSL2 Ubuntu/Debian distribution more like a Linux server by installing Docker Engine and Compose **inside that distribution**, without using Docker Desktop for MakerVault.

This is most appropriate for users who already understand WSL networking, service startup and Linux administration.

Follow Docker's official installation instructions for the Linux distribution running inside WSL, then verify:

```bash
sudo docker version
sudo docker compose version
sudo docker run --rm hello-world
```

After that, follow the normal [Linux installation guide](install.md). The MakerVault commands, `.env` format and container layout are the same.

There are two extra WSL responsibilities:

1. **Service lifecycle:** make sure Docker starts when the WSL distribution starts. Modern WSL distributions can use systemd when enabled.
2. **Host lifecycle/networking:** WSL is hosted by Windows. Windows sleep, shutdown, firewall rules and WSL networking still determine whether other devices can reach MakerVault.

Do not run this independent WSL Docker Engine at the same time as Docker Desktop and assume they share containers or volumes. They are separate Docker environments.

## Windows storage guidance

For a first Docker Desktop installation, use MakerVault's default named volumes:

```dotenv
MEDIA_STORAGE=makervault_media
KEY_STORAGE=makervault_keys
POSTGRES_STORAGE=makervault_postgres
REDIS_STORAGE=makervault_redis
BACKUP_STORAGE=makervault_backups
```

This is the least surprising configuration across Windows and WSL.

If you use Docker Desktop with a WSL checkout, Linux-side bind mounts such as `/home/yourname/makervault-data/media` are preferable to Windows-mounted paths such as `/mnt/c/... ` for Linux-heavy workloads.

If you deliberately use Windows bind mounts from PowerShell, Docker Desktop can translate Windows host paths, but permissions and path syntax differ from the Linux examples in this guide. Named volumes are therefore recommended until you specifically need host-visible folders.

See [Choose where your data lives](storage.md) before changing an existing installation. Changing a mount path does **not** move existing data.

## Backups on Windows

MakerVault's **Settings → Backup & restore** page is the recommended backup method on Windows too. Download the resulting `.mvbackup` file and keep another copy away from the PC running MakerVault.

The Linux-oriented host restore helper in the main backup chapter assumes a Linux shell and host tooling. If you are using Docker Desktop, the simplest disaster-recovery target is usually:

- another Docker Desktop installation with the same deployment files; or
- a Linux/WSL2 environment where the documented restore helper can run.

Always protect the database, media and matching encryption key as one recovery set.

## Updating MakerVault

From the same PowerShell, Windows Terminal or WSL shell in which you normally manage the installation:

```text
git pull --ff-only
docker compose pull
docker compose up -d
docker compose ps
```

Use `sudo docker compose ...` only when you installed Docker Engine directly inside Linux/WSL and your Linux user requires it.

## Which Windows method should I choose?

Use **Docker Desktop from Windows Terminal/PowerShell** if you want the easiest Windows setup.

Use **Docker Desktop + WSL2 integration** if you prefer Linux commands and want the closest experience to the normal MakerVault Linux guide.

Use **Docker Engine directly inside WSL2** only if you deliberately want to administer WSL as the Docker host and are comfortable managing its service and network lifecycle.

Whichever route you choose, do not maintain two separate MakerVault stacks in Docker Desktop and a second WSL Docker Engine unless you intentionally want two independent installations.

**Next:** [Configure your .env file](environment.md), then [First sign-in](first-sign-in.md).
