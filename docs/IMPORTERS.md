# MakerVault importers

MakerVault uses source adapters so external catalogue sites feed one internal data model rather than teaching the inventory UI about individual websites.

## v0.2 supported source

The first adapter supports board pages on **ESPBoards.dev**.

From the UI choose **Import URL**, paste an ESPBoards board URL, and MakerVault will:

1. validate the URL;
2. retrieve a bounded HTML response;
3. extract the board name, manufacturer, MCU family, memory, GPIO count, USB type, wireless capabilities, image/reference links and compatibility hints when present;
4. show a preview before anything is written;
5. create the board or merge missing source information into an existing matching board.

Imported provenance is stored in CatalogSource and extracted metadata is retained with the source record.

## Network safety

The v0.2 importer is intentionally allow-listed rather than acting as a general-purpose URL fetcher.

- HTTPS only.
- Only espboards.dev / www.espboards.dev.
- Embedded credentials and non-standard ports are rejected.
- DNS answers are rejected if they resolve to loopback, private, link-local, multicast, reserved or unspecified addresses.
- Redirects are revalidated at every hop.
- Responses must be HTML.
- The response body is capped at 4 MiB.
- Connection/read timeouts are enforced.

This prevents the importer from being used as an SSRF path into the Docker host or LAN.

## Future adapters

The same review-before-import workflow is intended for:

- SpoolmanDB
- 3D Filament Profiles
- FilamentsDB
- GitHub / GitLab repositories and releases
- manufacturer product pages
- marketplace APIs where permitted
- generic Schema.org Product / OpenGraph metadata

Marketplace integrations should prefer official APIs and permitted structured metadata rather than brittle scraping.
