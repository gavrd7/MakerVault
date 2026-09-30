# Catalogue enrichment and images

MakerVault deliberately separates a catalogue definition from a physical inventory item. A BME280 or ESP32-S3 board is defined once in the catalogue and any number of physical units can reference that definition.

## Starter catalogue

v0.2.1 ships an idempotent curated starter catalogue. It is intended to make a new installation immediately useful, not to be an exhaustive electronics database.

The seeder fills missing metadata on MakerVault-managed starter records but does not overwrite populated user fields. Running it repeatedly is safe:

~~~bash
python manage.py seed_catalogue
~~~

The starter data now includes broad board coverage and nearly 400 common component definitions across passives, semiconductors, lighting, displays, sensors, communications, audio, controls, power, switching, prototyping, connectors, storage, timing, motors/drivers, cameras, logic/level shifting, mechanical/thermal and test equipment.

## Structured component attributes

Component-specific facts live in the existing specifications JSON field. Common examples include:

~~~json
{
  "type": "environment",
  "interface": "I2C/SPI",
  "voltage": "3.3-5 V",
  "package": "module",
  "measures": ["temperature", "humidity", "pressure"]
}
~~~

This keeps the schema flexible enough for resistors, sensors, connectors, motors and modules without creating dozens of mostly-empty database columns.

## Source authority hierarchy

Catalogue enrichment is intentionally hierarchical. Adding more providers must not allow a weaker source to overwrite a stronger one.

1. **User / manual values** — priority 0. Explicit values are never overwritten automatically.
2. **Official manufacturer sources** — priority 10. Product pages, manufacturer documentation, datasheets and official APIs.
3. **MakerVault curated profiles** — priority 20. Version-controlled facts backed by authoritative references.
4. **Specialist structured catalogues** — priority 30. Domain-specific sources such as ESPBoards, OrcaSlicer and SpoolmanDB.
5. **Community / ecosystem sources** — priority 40. Maintained project documentation and repositories.
6. **Open media sources** — priority 50. Wikimedia Commons and Openverse for appropriately licensed imagery.
7. **Generic fallbacks** — priority 60. Used only for unresolved gaps.

Lower-priority providers only fill fields that remain empty after higher-priority sources have run. Catalogue metadata retains a bounded `source_trace` so maintenance and diagnostics can show which source was checked or selected.

For imagery, manufacturer/specialist source-page images may be referenced remotely when redistribution rights are not established. Openly licensed Commons/Openverse images may instead be cached into MakerVault media with attribution metadata.

## Image policy

The starter catalogue does not redistribute a large bundle of third-party product photographs. MakerVault instead supports local image ownership and source-aware caching:

- upload your own catalogue photo;
- paste a public HTTPS image URL from a manufacturer/source you are entitled to use;
- source adapters such as ESPBoards may provide an image URL which MakerVault can cache.

Every accepted image is decoded and re-encoded as WebP before storage. This removes metadata and avoids serving active image formats such as SVG.

Remote image fetching rejects non-HTTPS URLs, embedded credentials, non-standard ports, loopback/private/link-local/reserved network addresses, excessive redirects, unsupported content types and responses larger than 8 MiB.

Images are stored in the normal MakerVault media hierarchy, so a bind-mounted MEDIA_STORAGE=/mnt/Server/MakerVault/media is covered by the same backup strategy as the rest of the application data.
