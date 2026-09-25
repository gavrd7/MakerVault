# MakerVault v0.1.1

MakerVault is a self-hosted makerspace inventory and project system. This first runnable foundation includes:

- Django 5.2 LTS backend and authentication
- Local accounts, MFA-capable django-allauth, and optional generic OIDC client support
- React 19 frontend built into the application image
- PostgreSQL 18 database
- Redis + Celery background worker in the same MakerVault container as the web process
- Initial relational schema for boards, components, inventory, projects, BOMs, files, repositories, marketplace listings, filament/spools, printers, 3D models/revisions, and print history
- Storage selectable per deployment between Docker named volumes and normal host bind mounts
- Configurable timezone, language, currency, measurement system, PUID, PGID and umask
- Basic dashboard and spreadsheet-style inventory grid

Repository bootstrap commit. The full v0.1.1 source is imported in the following commit.
