geotessera's tile index cut to India (68-97.5 E, 6.5-37.5 N) for 2024: `registry.parquet` (tiles and their
hashes) and `landmasks.parquet`, same columns as geotessera 0.8's own files. src/tessera_tiles.py points
geotessera here instead of its 350 MB global index, which held 2.4 GB in memory and asked the server for
updates every start. To widen it (another year, another region), cut it again from geotessera's full files.
