<div class="guide-hero" markdown>
<span class="eyebrow">MakerVault / User guide</span>

# Your workshop, organised.

Learn to install MakerVault, record what you own and bring your projects, files and 3D printing together. Start with one project. Add the rest when you need it.

[Start here](getting-started/before-you-begin.md){ .md-button .md-button--primary }
[Follow a first project](getting-started/first-project.md){ .md-button }
</div>

!!! info "Current release: v1.1.0"
    MakerVault v1.1.0 improves background catalogue enrichment, restart-safe processing, provenance and image diagnostics. It retains first-run administrator setup, account and security management, and earlier project-management improvements. See [scope and verification](reference/about.md).

<div class="guide-grid" markdown>
<div class="guide-card" markdown>
### Set up your own server
No previous Docker experience assumed. Understand the few terms you need, install the application and create your first account.

[Installation walkthrough →](getting-started/install.md)
</div>
<div class="guide-card" markdown>
### Use it every day
Find a board, add the units you own, plan a build and keep its files together.

[Inventory and projects →](using/inventory.md)
</div>
<div class="guide-card" markdown>
### Organise 3D printing
Keep track of printers, camera feeds, physical spools, catalogue-matched filament products, models, print history and explicitly retained printed parts.

[3D printing →](using/printing.md)
</div>
<div class="guide-card" markdown>
### Keep your data safe
Back up the database, uploaded files and encryption key. Learn the update and recovery process before you need it.

[Back up and restore →](administration/backup.md)
</div>
</div>

## What MakerVault does

MakerVault is a self-hosted workshop management application. You open it in a web browser; your own server stores the data. You can use it without a printer integration or cloud account.

| What you want to record | Where it belongs | Example |
| --- | --- | --- |
| What a product is | Catalogue | An ESP32 development board and its specifications |
| What you actually own | Inventory | Three boards in drawer A2 |
| What you are building | Projects | A voice-assistant speaker and its bill of materials |
| Digital assets | Files | Firmware, wiring diagram, CAD and instructions |
| What you design and print | 3D Printing | Enclosure revisions, spools, live cameras and retained parts |
| Physical identification | Maker Tags | A QR/NFC/RFID identity linked to a spool or project |
| Connections in a build | Interactive Wiring | A diagram of boards, pins and wires |

Catalogue records are shared reference information. Personal workspaces are separated by account. A project is not currently a shared team folder. [Read about accounts](administration/accounts.md) before setting up a multi-user installation.

## Choose your route

- **New to self-hosting?** Read *Before you begin*, *Install MakerVault* and *First sign-in*, in that order.
- **Someone has already installed it for you?** Start with [First sign-in](getting-started/first-sign-in.md), then the guided project.
- **Already comfortable with Docker?** Use the installation settings table and [configuration reference](reference/configuration.md).
- **Want a domain name or single sign-on?** Finish the normal setup first, then visit [reverse proxies](advanced/reverse-proxy.md) and [OIDC](advanced/oidc.md).

Use the search box to find a feature or error. Each chapter can also be read as Markdown in GitHub.
