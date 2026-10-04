# Before you begin

**Goal:** decide where MakerVault will run and understand the few terms used in the installation.

## What you need

A computer that can stay on while you use MakerVault, reliable storage, an internet connection for installation and a modern web browser. A Debian or Ubuntu Linux server is the primary walkthrough in this guide. It can be a spare PC or a virtual machine. Keep enough spare disk space for the database, uploaded files, Docker images and backups; model files and retained versions can grow quickly. Extra temporary space is needed if you choose to build MakerVault locally.

The project does not yet publish a measured minimum RAM/CPU requirement or a fully tested NAS/ARM compatibility matrix. Do not treat a particular Raspberry Pi or NAS as validated just because it can run Docker.

| Host | Route |
| --- | --- |
| Debian / Ubuntu | Follow this guide and the linked official Docker installation for your exact OS release |
| Windows / macOS | Docker Desktop supplies Docker and Compose; shell paths and permissions differ from this Linux walkthrough |
| NAS / Portainer | The pre-built GHCR image removes the need to compile MakerVault, but Compose paths, permissions and storage still need adapting to that platform |

For a first installation, use the documented Linux route. You can access a Linux-hosted installation from Windows, macOS, a phone or a tablet without installing Docker on those client devices.

## Five useful terms

| Term | Plain-language meaning |
| --- | --- |
| Server / host | The computer running MakerVault |
| Docker image | A packaged application built from the project files |
| Container | A running instance of that package |
| Docker Compose | The tool that starts MakerVault, its database and its background queue together |
| Volume | Storage that survives replacing a container |

MakerVault uses three services: `makervault` for the app and background jobs, `postgres` for records, and `redis` for the queue/cache. The browser normally connects to host port **8765**. The app listens on port 8000 inside Docker; you usually leave that alone.

## Where you type commands

Use a terminal on the server, either directly or through SSH. Run the command blocks in order. Copy commands only, not surrounding headings. When a command uses `sudo`, it may ask for the Linux user's password; no characters appear as you type it.

`cd` changes folder. `mkdir` creates one. A filename starting with a dot, such as `.env`, is normally hidden in graphical file browsers. Commands later in this guide assume you are inside the cloned MakerVault repository. Normal installs use its deployment files while pulling the pre-built GHCR image; the same checkout can optionally be used to build from source.

## Decide on access and storage

Start with access from your trusted home network. Do not forward port 8765 through your router as part of the beginner installation. For HTTPS and a domain, use the [advanced proxy chapter](../advanced/reverse-proxy.md).

Keep Docker-managed named volumes for the simplest first setup. If you already organise server data in specific folders, read [Choose your storage](storage.md) before the first start. Changing a storage path later does not move the existing data.

## Repository access

MakerVault's source repository is public on GitHub. You can clone it without a GitHub account using the HTTPS URL shown in the installation guide. A GitHub account is only needed for actions such as opening issues, contributing changes or using authenticated GitHub features.

**Ready?** Continue to [Install MakerVault](install.md).
