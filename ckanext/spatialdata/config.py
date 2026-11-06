# encoding: utf-8

config = {
    "query_extent": "postgis",
    "postgis.field": "_geom",
    "postgis.mercator_field": "_geom_webmercator",
    "solr.index_field": "_geom",
    "solr.latitude_field": "latitude",
    "solr.longitude_field": "longitude",
    # Base URL of the Martin tile server (e.g. https://tiles.example.org).
    # Leave empty to hide tile links.
    "tileserver_url": "",
    # Must match `source_id_format` for the datastore connection in
    # martin/config.yaml. Placeholders: {table}, {column}, {schema}.
    "tile_source_id_format": "table.{table}.{column}",
}
