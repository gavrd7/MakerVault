# Catalogue enrichment and images

MakerVault deliberately separates a catalogue definition from a physical inventory item. A BME280 or ESP32-S3 board is defined once in the catalogue and any number of physical units can reference that definition.

## Starter catalogue

v0.2.1 ships an idempotent curated starter catalogue. It is intended to make a new installation immediately useful, not to be an exhaustive electronics database.

The seeder fills missing metadata on MakerVault-managed starter records but does not overwrite populated user fields. Running it repeatedly is safe:

~~~bash
python manage.py seed_catalogue
~~~

The starter data now includes broad board coverage and more than 130 common components across passives, semiconductors, lighting, displays, sensors, communications, audio, controls, power, switching, prototyping, connectors, storage, timing, motors/drivers, cameras, logic/level shifting, mechanical/thermal and test equipment.

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

## Image policy

The starter catalogue does not redistribute a large bundle of third-party product photographs. MakerVault instead supports local image ownership and source-aware caching:

- upload your own catalogue photo;
- paste a public HTTPS image URL from a manufacturer/source you are entitled to use;
- source adapters such as ESPBoards may provide an image URL which MakerVault can cache.

Every accepted image is decoded and re-encoded as WebP before storage. This removes metadata and avoids serving active image formats such as SVG.

Remote image fetching rejects non-HTTPS URLs, embedded credentials, non-standard ports, loopback/private/link-local/reserved network addresses, excessive redirects, unsupported content types and responses larger than 8 MiB.

Images are stored in the normal MakerVault media hierarchy, so a bind-mounted MEDIA_STORAGE=/mnt/Server/MakerVault/media is covered by the same backup strategy as the rest of the application data.
