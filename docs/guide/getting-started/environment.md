# Configure your .env file

**Goal:** understand what needs changing before the first start, and leave the remaining settings at sensible defaults.

Work through this chapter at **step 3 of installation**, after downloading MakerVault and before starting its containers. It assumes direct access on your trusted local network. Domain names, HTTPS and OIDC have their own advanced chapters.

## What is .env?

`.env` is a plain-text settings file in the same folder as `compose.yaml`. Docker Compose reads it to configure your installation. MakerVault's Compose file also passes settings from it to the application container.

| File | Purpose | Should you edit it? |
| --- | --- | --- |
| `.env.example` | The project's example settings, updated with the source code | Normally no; use it as a reference |
| `.env` | Your installation's real settings and secrets | Yes; this is your working configuration |
| `compose.yaml` | Describes the services, ports and storage connections | Normally leave it alone for this setup |

The leading dot makes `.env` a hidden file on many systems. Its exact name matters: `.env.txt` is a different file. It is not a Python script and you do not need to run or `source` it.

## Create and edit it

For a **new installation only**, run these inside the downloaded MakerVault folder:

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

`cp` creates your working copy. `chmod 600` makes it readable/writable only by its owning Linux user. `nano` opens a text editor. Do not repeat the copy command over an existing configuration: it would replace your saved settings and secrets.

In nano, use the arrow keys to move, edit the text, then press **Ctrl+O**, **Enter**, **Ctrl+X** to save and exit.

### Read a setting

```dotenv
# This is a comment explaining the line below.
MAKERVAULT_PORT=8765
```

The name on the left identifies the setting; the value on the right is your choice. Lines beginning with `#` are comments and do not configure anything. A commented-out example only becomes active when you remove the leading `#`.

Use one setting per line with no spaces around `=`. Keep names exactly as supplied, and edit the existing line rather than adding another copy further down. `true` and `false` are switches. An empty value such as `EMAIL_HOST=` means that no value has been supplied; it is not the same as `false`.

Use straight quotes if quoting is needed, not curly “smart quotes”. Compose can interpret dollar signs in unquoted or double-quoted values. Single quotes preserve literal values; the generated secrets below avoid dollar signs, spaces and comment characters, so they can be pasted without quotes. See Docker's [environment-file syntax](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/) for special cases.

## What must I change?

For a new, direct-LAN installation:

| Priority | Settings | Your action |
| --- | --- | --- |
| **Replace before starting** | `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` | Generate two different random values below |
| **Match your address** | `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Add your real server IP/hostname in the correct format |
| **Match direct access** | `TRUST_PROXY_HEADERS`, `ALLAUTH_TRUSTED_PROXY_COUNT` | Use `false` and `0` respectively |
| **Choose before first start** | The six `*_STORAGE` entries | Keep named-volume defaults or choose [bind mounts](storage.md) |
| **Review your preferences** | Timezone, language, currency and measurements | Change if the supplied UK/metric defaults do not suit you |
| **Usually leave alone** | Database/Redis internal addresses, concurrency and catalogue limits | Keep defaults for the standard deployment |
| **Optional version pin** | `MAKERVAULT_IMAGE` | Leave unset to use the default GHCR `latest` image, or pin a published version |
| **Optional later** | OIDC, SMTP email, administrator bootstrap | Leave disabled/blank until you need them |

You do not need to fill every empty line. Many are deliberately empty because their feature is optional.

## Choose or pin the MakerVault image

The normal Compose deployment pulls MakerVault from GitHub Container Registry:

```text
ghcr.io/gavrd7/makervault:latest
```

You normally do not need to add anything to `.env`. If you want to stay on a specific release until you deliberately upgrade, set:

```dotenv
MAKERVAULT_IMAGE=ghcr.io/gavrd7/makervault:1.0.0
```

This setting controls only the MakerVault application image. It does not change your database or storage. Users following the build-it-yourself route use `compose.build.yaml`, which replaces the published image with a locally built one.

## Generate the secrets

There are three different secrets to understand. They are not interchangeable.

| Secret | What it does | How it is created |
| --- | --- | --- |
| Django secret key | Used by the web application for signing/security functions | You generate it once for `DJANGO_SECRET_KEY` |
| PostgreSQL password | Lets the app authenticate to its database | You generate it once for `POSTGRES_PASSWORD` |
| Private-file encryption key | Encrypts/decrypts your private uploaded files | MakerVault generates it automatically in persistent key storage by default |

Your **login password** is separate again: create it when prompted by `createsuperuser` later in installation.

### 1. Generate the Django key

Run this command in the terminal, not inside nano. If nano is open, save and exit first:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

It prints a long random string. Copy the complete output, reopen `nano .env`, and replace only the value after `DJANGO_SECRET_KEY=`. The result should have the form below, but with your generated value:

```dotenv
DJANGO_SECRET_KEY=PASTE_YOUR_FIRST_GENERATED_VALUE_HERE
```

Do not use that placeholder literally. Generate secrets on your own machine; do not use an example key from a guide or a public key-generation website.

### 2. Generate a separate database password

Run the same Python command again. Its new output will be different. Put that second value after `POSTGRES_PASSWORD=`:

```dotenv
POSTGRES_PASSWORD=PASTE_YOUR_SECOND_GENERATED_VALUE_HERE
```

Keep these values stable across restarts and normal updates. Store the completed `.env` in your protected backup set.

### 3. Let MakerVault manage the file-encryption key

For the default deployment, leave:

```dotenv
KEY_STORAGE=makervault_keys
MAKERVAULT_STORAGE_KEY_FILE=/app/keys/private_storage.key
```

If using bind mounts, change `KEY_STORAGE` to your chosen host key folder, but keep the `/app/keys/private_storage.key` value: that path is **inside the container**.

Leave `MAKERVAULT_STORAGE_KEY` commented out. Startup generates a correctly formatted random key once and keeps it in the key storage. Back it up along with media and the database. Managed backups keep all three together. It is not a file you need to create manually for normal setup.

!!! warning "Existing installations: do not regenerate secrets as an update step"
    Replacing the file-encryption key makes existing private uploads unreadable. Changing only `POSTGRES_PASSWORD` does not change the password already held by an existing PostgreSQL database and can prevent the app connecting. Changing the Django key can invalidate signed data such as sessions or reset links. Preserve the existing values during upgrades; deliberate credential rotation is a separate task.

## Configure the browser address

Suppose the server's LAN address is `192.168.1.50` and you want to use port `8765`:

```dotenv
MAKERVAULT_BIND_ADDRESS=0.0.0.0
MAKERVAULT_PORT=8765
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8765,http://192.168.1.50:8765
TRUST_PROXY_HEADERS=false
ALLAUTH_TRUSTED_PROXY_COUNT=0
```

Replace the example IP with yours. `0.0.0.0` means “listen on all host IPv4 interfaces”; it is not the address to type in your browser. Keep access limited to the intended network.

**Allowed hosts** are the names/IPs MakerVault accepts. They have no `http://` and no port. **Trusted origins** include the scheme and port, and identify the browser addresses you trust for requests such as saving forms. Do not include a page path or trailing slash in these origin examples.

If you choose port `9000`, set `MAKERVAULT_PORT=9000`, change `:8765` to `:9000` in trusted origins, and browse to `http://192.168.1.50:9000`. The port inside the app container stays `8000`; `DATABASE_PORT=5432` is unrelated.

For direct HTTP access, retain:

```dotenv
DJANGO_DEBUG=false
DJANGO_SECURE_COOKIES=false
DJANGO_SECURE_SSL_REDIRECT=false
DJANGO_HSTS_SECONDS=0
TRUST_X_FORWARDED_HOST=false
```

The HTTPS settings are not “extra protection” switches to turn on before you have HTTPS: doing so can break direct HTTP sign-in. Configure them as part of the [reverse-proxy walkthrough](../advanced/reverse-proxy.md).

## Understand the remaining sections

| Section | Meaning and usual action |
| --- | --- |
| Locale/time | `TZ` is the container timezone; `DJANGO_TIME_ZONE` is the app timezone. Normally keep them the same, e.g. `Europe/London`. `DJANGO_LANGUAGE_CODE=en-gb` selects British English. Currency/measurement settings express preferences; they do not convert existing money amounts. |
| Container permissions | `PUID` and `PGID` identify the Linux user/group for app storage, especially bind mounts. `UMASK=0022` controls permissions on newly created files/directories; it is not a user ID. Keep it and `FIX_PERMISSIONS=true` unless you deliberately manage ownership yourself. See [storage choices](storage.md). |
| Storage | Separate locations hold media, private-file keys, database, Redis data, managed recovery bundles and optional native-TLS identity. Set these before entering real data. They do not identify the source-code folder. |
| Registration/admin | Keep `ALLOW_LOCAL_REGISTRATION=false` for accounts created by an administrator. Leave `MAKERVAULT_ADMIN_PASSWORD` empty when using interactive `createsuperuser`. A non-empty bootstrap password is applied at startup, so it can override later password changes. |
| Legacy owner | Leave `MAKERVAULT_LEGACY_OWNER_USERNAME` blank on a new installation. It is for ambiguous ownership during upgrades from before v0.7. |
| OIDC | External single sign-on. Leave `OIDC_ENABLED=false` and credentials empty until following [OIDC setup](../advanced/oidc.md). Client credentials come from your provider, not the Python generator above. |
| Email | Leave `EMAIL_HOST` blank if not using SMTP. Password-reset email will not be sent. SMTP credentials are provided by your mail service; see [email setup](../advanced/email.md). |
| PostgreSQL | Keep database name/user at `makervault`, `DATABASE_HOST=postgres` and `DATABASE_PORT=5432` for the supplied Compose deployment. `postgres` is an internal Docker service name, not your server's LAN hostname. Change the password before first start. |
| Catalogue enrichment/images | Keep defaults to allow reference-data maintenance. Configure schedules in **Settings → Library updates**. Limits/retry days control how much work is attempted and how soon sources are revisited; a refresh cannot guarantee every missing picture/specification will be found. |
| Printer/filament catalogues | Optional external reference feeds, distinct from live printer connections. Normally retain the supplied sources/ref. |
| Redis/worker | `REDIS_URL` identifies the internal queue/cache service. `WEB_CONCURRENCY` and `CELERY_CONCURRENCY` control worker counts; larger numbers can use more memory and are not automatically faster. Keep defaults initially. |
| Upload settings | Byte-based Django request/buffering settings. They are not a universal maximum file-size switch; app and proxy limits also apply. Retain defaults unless diagnosing a specific requirement. |

## Validate and apply

Save the file, then run from its folder:

```bash
sudo docker compose config --quiet
```

No output and a successful exit means Compose could parse the configuration. It does **not** prove the database credentials, network address or storage choices are correct.

For the first launch, return to [installation step 4](install.md#4-pull-and-start-makervault-recommended) and build the app. For an existing installation after an ordinary settings edit:

```bash
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 makervault
```

A plain `restart` does not load changed container environment settings. Check sign-in and a saved record after the change.

## What changes when MakerVault is updated?

Keep your existing `.env`. Compare it with the new `.env.example` and read the release notes. Add newly required settings or update documented changed settings; do not copy the entire new example over your working file.

| Change you are making | What to review |
| --- | --- |
| New server IP/hostname | Allowed hosts, trusted origins, bookmark and any proxy/provider callback URLs |
| New browser-facing port | `MAKERVAULT_PORT`, origins and bookmark |
| New timezone/currency preference | Corresponding locale values; verify displayed results |
| Enabling HTTPS | Follow the HTTPS/reverse-proxy chapter; choose reverse-proxy TLS or the optional native 8443 listener deliberately |
| Moving stored data | Back up and restore to the new location; changing a path is not migration |
| Normal app update | Preserve secrets and storage paths; review new example settings |

Keep `.env` out of Git and support screenshots. Use `config --quiet` for validation: ordinary `docker compose config` can print expanded secrets. If a setting still appears unchanged after recreation, check for duplicate entries and environment variables exported by your shell or deployment tool that override Compose values.
