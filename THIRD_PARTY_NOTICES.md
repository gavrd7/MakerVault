# MakerVault third-party notices

MakerVault source code is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later). This file describes material that is not relicensed under MakerVault's software licence.

## Runtime catalogue media

MakerVault can download and cache catalogue images at runtime. Those images remain subject to the licence and terms of their original source. MakerVault records provider, source page, author and licence metadata when available.

The default automatic image source is Wikimedia Commons. MakerVault v0.2.3 accepts automatic Commons results only when the reported licence is compatible with normal open redistribution: CC0/Public Domain, CC BY, or CC BY-SA. Creative Commons licences require attribution except CC0; ShareAlike material retains its ShareAlike obligations.

ESPBoards publishes its own pinout diagrams and board illustrations under CC BY-NC 4.0 with attribution requirements. Because that licence restricts commercial use, automatic ESPBoards image caching is disabled by default. A deployment that explicitly enables it is responsible for complying with ESPBoards' terms and preserving attribution.

No runtime-downloaded catalogue image is relicensed under AGPL merely because MakerVault caches or displays it.

## SpoolmanDB filament catalogue

MakerVault can query the public SpoolmanDB filament catalogue at runtime to help users create native filament-product records. SpoolmanDB is an independent project and its catalogue/software repository is distributed under the MIT License. Imported MakerVault records retain their SpoolmanDB source identifier, source URL and licence metadata.

MakerVault does not require SpoolmanDB to operate. Once imported, filament records are stored in MakerVault and remain available if the external catalogue is unavailable or disabled.

## OrcaSlicer printer catalogue

MakerVault can use the public OrcaSlicer printer profile manifests as an optional runtime source for 3D-printer manufacturer/model catalogue breadth. OrcaSlicer is an independent project distributed under the GNU Affero General Public License v3.0 (AGPL-3.0).

MakerVault reads OrcaSlicer's vendor and machine-model manifest names and stores source provenance on imported catalogue records. It does not copy OrcaSlicer process, filament or G-code presets into MakerVault. Existing populated MakerVault hardware specifications remain authoritative and are not overwritten by catalogue refreshes.

The upstream project is available from the OrcaSlicer/OrcaSlicer repository on GitHub. MakerVault remains usable when this source is unavailable or disabled.

## go2rtc camera compatibility relay

MakerVault bundles the go2rtc media relay (v1.9.14) for browser compatibility with Creality K2 WebRTC camera streams. go2rtc is an independent project distributed under the MIT License, Copyright (c) 2022 Alexey Khit. Its licence text is included in `/app/licenses/go2rtc-LICENSE` in the MakerVault container.

MakerVault uses a restricted go2rtc configuration: only the local stream/WebRTC API is enabled, the management API listens on loopback only, and the relay is used only for MakerVault-managed camera compatibility.

## User-provided media

Images and files uploaded by users remain subject to the rights and licences applicable to those files. Users are responsible for ensuring they have permission to upload, store and redistribute such material.

## Software dependencies

MakerVault is built with third-party open-source libraries and container images, including Django, django-allauth, Celery, Redis clients, Gunicorn, React, AG Grid Community, Vite, Three.js, Pillow, Beautiful Soup and PostgreSQL/Redis container images. Each dependency remains under its own upstream licence. Consult the package metadata and upstream projects for the authoritative licence text and notices.

## Attribution in the application

Open **About → Media attribution** in a running MakerVault instance to see the third-party image records actually cached by that installation.

This notice is informational and is not a substitute for the licence terms of any third-party work.


## Openverse

MakerVault can use the Openverse API as a discovery index for openly licensed catalogue images. Openverse does not become the owner or licence issuer of the indexed media. MakerVault retains the upstream creator, landing/source page and reported licence metadata and only automatically accepts CC0/Public Domain, CC BY and CC BY-SA licence families.

Users should follow the attribution and ShareAlike requirements of the original work. MakerVault does not relicense runtime-downloaded Openverse media under the MakerVault software licence.
