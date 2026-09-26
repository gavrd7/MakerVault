# MakerVault third-party notices

MakerVault source code is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later). This file describes material that is not relicensed under MakerVault's software licence.

## Runtime catalogue media

MakerVault can download and cache catalogue images at runtime. Those images remain subject to the licence and terms of their original source. MakerVault records provider, source page, author and licence metadata when available.

The default automatic image source is Wikimedia Commons. MakerVault v0.2.3 accepts automatic Commons results only when the reported licence is compatible with normal open redistribution: CC0/Public Domain, CC BY, or CC BY-SA. Creative Commons licences require attribution except CC0; ShareAlike material retains its ShareAlike obligations.

ESPBoards publishes its own pinout diagrams and board illustrations under CC BY-NC 4.0 with attribution requirements. Because that licence restricts commercial use, automatic ESPBoards image caching is disabled by default. A deployment that explicitly enables it is responsible for complying with ESPBoards' terms and preserving attribution.

No runtime-downloaded catalogue image is relicensed under AGPL merely because MakerVault caches or displays it.

## User-provided media

Images and files uploaded by users remain subject to the rights and licences applicable to those files. Users are responsible for ensuring they have permission to upload, store and redistribute such material.

## Software dependencies

MakerVault is built with third-party open-source libraries and container images, including Django, django-allauth, Celery, Redis clients, Gunicorn, React, AG Grid Community, Vite, Three.js, Pillow, Beautiful Soup and PostgreSQL/Redis container images. Each dependency remains under its own upstream licence. Consult the package metadata and upstream projects for the authoritative licence text and notices.

## Attribution in the application

Open **About → Media attribution** in a running MakerVault instance to see the third-party image records actually cached by that installation.

This notice is informational and is not a substitute for the licence terms of any third-party work.
