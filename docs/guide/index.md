<div class="guide-hero" markdown>
<span class="eyebrow">MakerVault / User guide</span>

# Your workshop, organised.

Learn to install MakerVault, record what you own and bring your projects, files and 3D printing together. Start with one project. Add the rest when you need it.

[Start here](getting-started/before-you-begin.md){ .md-button .md-button--primary }
[Follow a first project](getting-started/first-project.md){ .md-button }
</div>

!!! info "Edition: v0.7.0.1 · Before v1"
    This guide describes the current implementation, checked against source commit `59d12f81a2941178bca4e6fb1cea68f2081c60b4` on 29 September 2026. It is the foundation for the v1 guide, not a promise that development builds will never change. See [scope and verification](reference/about.md).

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
Keep track of printers, physical spools, model revisions and the material cost of your prints.

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
| What you design and print | 3D Printing | Enclosure revisions, spools and print history |

Catalogue records are shared reference information. Personal workspaces are separated by account. A project is not currently a shared team folder. [Read about accounts](administration/accounts.md) before setting up a multi-user installation.

## Choose your route

- **New to self-hosting?** Read *Before you begin*, *Install MakerVault* and *First sign-in*, in that order.
- **Someone has already installed it for you?** Start with [First sign-in](getting-started/first-sign-in.md), then the guided project.
- **Already comfortable with Docker?** Use the installation settings table and [configuration reference](reference/configuration.md).
- **Want a domain name or single sign-on?** Finish the normal setup first, then visit [reverse proxies](advanced/reverse-proxy.md) and [OIDC](advanced/oidc.md).

Use the search box to find a feature or error. Each chapter can also be read as Markdown in GitHub.
