# Glossary

| Term | Meaning in this guide |
| --- | --- |
| Administrator / superuser | A full application administrator |
| Allocation | A quantity of inventory reserved for a project BOM line |
| Bind mount | A host folder mounted into a container |
| BOM | Bill of materials: the parts and amounts required for a build |
| Catalogue | Reusable product/reference definitions, separate from physical ownership |
| Celery / Beat | Background task execution and its scheduler |
| Container | A running packaged service |
| Compose | The tool that coordinates this app, PostgreSQL and Redis |
| CSRF | A web protection that checks whether a form request comes from a trusted origin |
| Editor / Viewer | Seeded permission groups; they do not grant another user's private records |
| Encryption at rest | Uploaded private bytes are encrypted while stored; the running server can decrypt them with its key |
| Environment file / `.env` | Local deployment settings and secrets |
| File version | A preserved set of uploaded bytes in a file's history |
| Filament product | Reusable product/material/colour information |
| GiB | 1,073,741,824 bytes; the unit used by quota controls |
| Host | The computer running Docker |
| Image | A container package; in catalogue contexts, a picture instead |
| Inventory | The physical stock/assets you actually own |
| Migration | A controlled change to stored database structure or existing data |
| Model revision | A particular design iteration with links to its files |
| Named volume | Persistent storage managed by Docker |
| OIDC | OpenID Connect, a standard for signing in through an identity provider |
| Origin | Scheme, hostname and port, e.g. `http://192.168.1.50:8765` |
| Physical spool | One real reel of filament, distinct from its product definition |
| Port | A numbered network endpoint; MakerVault normally uses host port 8765 |
| PostgreSQL | The database holding structured application records |
| Quota | An application limit on a user's stored upload usage |
| Redis | Queue/cache storage used by background work |
| Repository | A version-controlled collection of source files |
| Reverse proxy | A service receiving browser requests and forwarding them to MakerVault |
| Self-hosted | Run on a server you operate rather than as a hosted application subscription |
| Staff | An account flag permitting access to administrative interfaces subject to permissions |
| STL / 3MF | Formats used for printable meshes or packaged 3D/slicer data |
