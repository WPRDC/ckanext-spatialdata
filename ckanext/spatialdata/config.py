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
    # Martin source id of the map view's tile function (tile_function.sql);
    # follows the function source_id_format in martin/config.yaml.
    "tile_function_source": "public.spatialdata_tiles",
    # Map resource view (spatialdata_view).
    # MapLibre style JSON used as the basemap under the resource's tiles.
    "basemap_style_url": "https://tiles.openfreemap.org/styles/positron",
    # Lowest zoom the tile server serves for datastore tables; should match
    # `minzoom` for the datastore connection in martin/config.yaml. Below it
    # the map asks the user to zoom in.
    "tile_minzoom": "0",
}
