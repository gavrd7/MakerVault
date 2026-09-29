# Troubleshooting

Start with the precise error and the smallest affected area. Do not delete volumes or reinitialise the database to see whether an error disappears.

## Collect a basic status report

Run from your source folder:

```bash
sudo docker compose ps
sudo docker compose logs --tail=150 makervault
sudo docker compose logs --tail=100 postgres redis
df -h
git rev-parse HEAD
```

Read logs before sharing them. Redact credentials, tokens, sensitive hostnames and personal file information. Do not paste `.env` or unredacted `docker compose config` output into an issue.

| Symptom | Check first | Next action |
| --- | --- | --- |
| Repository not found / 404 | Private repository access and correct URL | Authenticate an authorised GitHub account; request access from the maintainer |
| `docker compose` not found | Compose plugin installation | Follow the official Docker instructions for your OS |
| Cannot connect to Docker | Docker service and permissions | Try the documented `sudo docker` commands; check Docker is running |
| Port already allocated | Another program/container uses the host port | Choose another `MAKERVAULT_PORT`, update origins and browser URL, then recreate |
| Browser cannot connect | Correct LAN IP, port, server power, firewall and container state | Test from the server and from the LAN; inspect restart/errors |
| Bad Request / `DisallowedHost` | `DJANGO_ALLOWED_HOSTS` | Add the actual hostname/IP without scheme or port, then recreate |
| CSRF verification fails | Exact browser origin and proxy scheme | Set trusted origins with scheme and port where used; review HTTPS headers |
| Login loops on local HTTP | Secure cookies enabled without HTTPS | Use verified HTTPS or restore the direct-LAN settings |
| HTTPS redirect loop | Forwarded scheme and trusted proxy topology | Correct the proxy header/configuration before enabling SSL redirect |
| No initial login works | Whether you created a superuser | Use `createsuperuser`; there is no default password |
| No password-reset email | Empty/incorrect SMTP settings or account email | Configure/test SMTP or use the authorised local recovery command |
| Missing Add/Edit/Delete | Account groups and specific permissions | Ask the administrator; do not assume every Editor has every delete permission |
| Empty private workspace | Signed-in username and upgrade ownership | Use the correct account; check ownership migration before altering data |
| Upload refused | Quota, file/request size, proxy limit, disk space | Read the actual error; adjust the relevant limit or free space safely |
| Missing encryption key | Correct key volume/path and matching backup | Restore the original key; never generate a substitute for existing blobs |
| Database authentication fails | Existing volume's database credentials | Restore the correct `.env`; changing `POSTGRES_PASSWORD` does not reset an existing database role |
| Missing catalogue images/specs | Maintenance settings and supported sources | Run a check and allow time; unknown data is not always an error |
| Integration disconnected | Endpoint, credentials, printer power and container network | Test manually, then read the provider-specific error |
| Allocation rejected | Free quantity, status and project conflicts | Release/correct existing allocations before changing inventory |
| Model preview/analysis fails | File format, geometry validity, size and browser WebGL | Try a known small STL/3MF and validate the file in your slicer |

## Files disappear after changing storage

Stop making changes. Check whether `.env` points to a new empty bind directory or a different named volume. Existing data may still be in the original storage. Restore the original mapping or follow a deliberate backup/restore migration. Do not delete either copy until the intended dataset is identified.

## Ask for help effectively

Include the MakerVault version/commit, OS, install method, affected feature, exact error, time and steps to reproduce. Explain whether it previously worked and what changed. Attach a redacted screenshot or short log excerpt, not credentials or the entire database.

Use the repository's issue tracker for reproducible application problems. Do not publish private security details in a public issue; agree a private reporting route with the maintainer.
