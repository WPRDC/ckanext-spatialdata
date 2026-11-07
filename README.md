[![CKAN](https://img.shields.io/badge/ckan-2.10.1-orange.svg?style=flat-square)](https://github.com/ckan/ckan)

# ckanext-spatialdata

_A CKAN extension that provides geospatial awareness of datastore data._

<img src=".github/wprdc-mark-light.png#gh-light-mode-only" height="50px" alt="WPRDC Logo"/>
<img src=".github/wprdc-mark-dark.png#gh-dark-mode-only" height="50px" alt="WPRDC Logo"/>


__A product of the [Western Pennsylvania Regional Data Center](https://www.wprdc.org).__

[Built upon the work fo the Natural History Museum in London.](#acknowledgements)

## Overview

This extension provides geospatial awareness of datastore data. This includes:

- Geospatial searches within datasets;
- Pushing GeoJSON data (properties and geometries) in to the datastore;
- Support for [PostGIS](http://postgis.net);
- Support for tile servers that injest PostGIS data. (e.g. [martin](https://github.com/maplibre/martin)).
- _todo: Spatial extent of datastore searches_

## Installation

Path variables used below:

- `$INSTALL_FOLDER` (i.e. where CKAN is installed), e.g. `/usr/lib/ckan/default`
- `$CONFIG_FILE`, e.g. `/etc/ckan/default/development.ini`

1. Clone the repository into the `src` folder:

  ```bash
  cd $INSTALL_FOLDER/src
  git clone https://github.com/wprdc/ckanext-spatialdata.git
  ```

2. Activate the virtual env:

  ```bash
  . $INSTALL_FOLDER/bin/activate
  ```

3. Install the requirements from requirements.txt:

  ```bash
  cd $INSTALL_FOLDER/src/ckanext-spatialdata
  pip install -r requirements.txt
  ```

4. Run setup.py:

  ```bash
  cd $INSTALL_FOLDER/src/ckanext-spatialdata
  python setup.py develop
  ```

5. Add 'spatialdata' to the list of plugins in your `$CONFIG_FILE`:

  ```ini
  ckan.plugins = ... spatialdata
  ```

## Configuration

There are a number of options that can be specified in your .ini config file. They all have defaults set, so none are
_required_.

| Name                                 | Description                            | Default            |
|--------------------------------------|----------------------------------------|--------------------|
| `spatialdata.postgis.field`          | WGS data field in the PostGIS database | \_geom             |
| `spatialdata.postgis.mercator_field` | Mercator field in the PostGIS database | _geom\_webmercator |
| `spatialdata.tileserver_url`          | Public base URL of the Martin tile server, used for TileJSON links in the dataset page's "Spatially enabled" modal. Empty hides the links. | _(empty)_ |
| `spatialdata.tile_source_id_format`   | Tile source id pattern; must match `source_id_format` for the datastore connection in Martin's config. Placeholders: `{table}`, `{column}`, `{schema}`. | table.{table}.{column} |
| `spatialdata.basemap_style_url`       | MapLibre style JSON used as the basemap in the Map view. | https://tiles.openfreemap.org/styles/positron |
| `spatialdata.tile_minzoom`            | Lowest zoom the tile server serves for datastore tables. Below it the Map view asks the user to zoom in. | 0 |

## Further Setup

### PostGIS

To use this extension, your PostgreSQL database must have [PostGIS](http://postgis.net) support.

1. Install the correct version of PostGIS for your version of
   PostgreSQL: https://postgis.net/documentation/getting_started/

2. You will then need to create PostGIS columns on your resources. Invoking the command below will create the two
   columns named above (`spatialdata.postgis.field` and `spatialdata.postgis.mercator_field`) on table `$RESOURCE_ID`.
   One represents the [WGS](http://en.wikipedia.org/wiki/World_Geodetic_System) (World Geodetic System) data, and one
   uses the web mercator projection, which is useful for generating maps.
    ```bash
    ckan spatialdata create-columns $RESOURCE_ID -c $CONFIG_FILE
    ```

## Map view

The plugin provides a `spatialdata_view` resource view ("Map") that draws a georeferenced
resource with [MapLibre GL JS](https://maplibre.org/) (vendored in `assets/vendor/maplibre-gl`),
using the resource's vector tiles from the tile server. Points, lines and polygons are all
drawn, and clicking a feature shows its attributes.

- It is offered for resources with `spatialdata_active` set, and only when
  `spatialdata.tileserver_url` is configured.
- A Map view is added automatically when a georeferencing job completes. For resources
  georeferenced before this existed, add it from the resource's "Views" tab, or run
  `ckan views create spatialdata_view`.
- Each Map view has a **Map style** setting: a JSON list of
  [MapLibre layers](https://maplibre.org/maplibre-style-spec/layers/) (fill, line, circle,
  symbol, heatmap or fill-extrusion) drawn from the resource, edited in a code editor
  (CodeMirror 5, vendored in `assets/vendor/codemirror`). `id`, `source` and `source-layer`
  are filled in. Style by column with expressions such as `["get", "column"]`. The editor
  checks the style as you type with MapLibre's style validator (`maplibre-gl-style-spec`,
  vendored in `assets/vendor/maplibre-gl-style-spec`) and won't save while it has problems;
  Preview shows the result on the map. The server only checks the JSON, list shape and layer
  types, so styles set through the API aren't fully validated; problems in those show as
  errors on the map. The default style (`lib/map_style.py`) is used when none is set.
- The browser loads tiles straight from the tile server, so the tile server must send CORS
  headers that allow the CKAN site's origin.

## Usage

### Geospatial metadata

GeoJSON files can be parsed without any extra metadata.

To parse tabular files, you must update the resources extra fields.

The file can't be parsed unless either `spatialdata_longitude_field` AND `spatialdata_latitude_field` are provided
OR `spatialdata_wkt_field` is provided.

#### Writable Fields

| Field                         | Description                                                                                                                                                                                                                            |
|-------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| spatialdata_longitude_field   | Name of field that contains longitude data                                                                                                                                                                                             | 
| spatialdata_latitude_field    | Name of field that contains latitude data                                                                                                                                                                                              | 
| spatialdata_wkt_field         | Name of field that contains Well-Known Text data                                                                                                                                                                                       | 
| spatialdata_fields_definition | **_Optional_**, **_Only used with GeoJSON resources._** Must be a valid [Fields](https://docs.ckan.org/en/2.10/maintaining/datastore.html#fields) json object. Used to provide field types when loading a GeoJSON into the datastore.' |

#### Read-only fields

| Field                         | Description                                         | 
|-------------------------------|-----------------------------------------------------|
| spatialdata_active            | is `true` if resource has been georeferenced        | 
| spatialdata_status            | status of georeferencing job                        | 
| spatialdata_last_geom_updated | timestamp of last time georeferencing was conducted | 

### Actions

#### `spatialdata_submit`

Submit resource qeoreferencing job to be processed by CKAN worker.

```shell
curl -X POST https://data.wprdc.org/api/action/spatialdata_submit \
   -H 'Content-Type: application/json' \
   -H 'Authorization: <API_KEY>' \
   -d '{"resource_id": "<RESOURCE_ID>"}'
```

```python
from ckan.plugins import toolkit

toolkit.get_action('spatialdata_submit')(
    context,
    {
        'resource_id': '<RESOURCE_ID>',
    }
)
```

#### `spatialdata_submit_package`

Submit every eligible resource in a dataset for georeferencing. A resource is eligible if it is a
GeoJSON file, or if it is in the datastore and has latitude/longitude or WKT fields configured.
Sysadmins only.

```shell
curl -X POST https://data.wprdc.org/api/3/action/spatialdata_submit_package \
   -H 'Content-Type: application/json' \
   -H 'Authorization: <API_TOKEN>' \
   -d '{"id": "<DATASET_ID_OR_NAME>"}'
```

Returns the dataset id, the ids of the resources that were `submitted`, and the resources that were
`skipped`, each with a `reason`:

```json
{
  "package_id": "<DATASET_ID>",
  "submitted": ["<RESOURCE_ID>"],
  "skipped": [{"resource_id": "<RESOURCE_ID>", "reason": "No latitude/longitude or WKT field configured on the resource."}]
}
```

#### `spatialdata_status`

Get georeferencing status of a resource with the following data:

| Field          | Description                                       |
|----------------|---------------------------------------------------|
| job_id         | ID of CKAN worker job                             |
| status         | Status of the worker job                          |
| last_updated   | Timestamp of last time the **status** was updated |
| rows_completed | Number of rows parsed                             |
| notes          | Description of current status                     |

```shell
curl -X POST https://data.wprdc.org/api/3/action/spatialdata_status \
   -H 'Content-Type: application/json' \
   -d '{"resource_id": "<RESOURCE_ID>"}'
```

```python
from ckan.plugins import toolkit

status = toolkit.get_action('spatialdata_status')(
    context,
    {
        'resource_id': '<RESOURCE_ID>',
    }
)
```

#### `datastore_search`

Searching by geospatial fields involves passing a custom filter to `datastore_search`. The filter `_tmgeom` contains
a [WKT](http://en.wikipedia.org/wiki/Well-known_text) (Well-Known Text) string representing the area to be searched (
currently, only the types `POLYGON` or `MULTIPOLYGON` will work). e.g.:

```python
from ckan.plugins import toolkit

search_params = {
    'resource_id': '<RESOURCE_ID>',
    'filters': '_tmgeom:POLYGON(36 114, 36 115, 37 115, 37 114, 36 114)'
}
search = toolkit.get_action(u'datastore_search')(context, search_params)
```

### CLI

#### `spatialdata`

1. `create-columns`: create the PostGIS columns on the `$RESOURCE_ID` table.
    ```bash
    ckan spatialdata create-columns $RESOURCE_ID --geom-type=$GEOM_TYPE -c $CONFIG_FILE
    ```

2. `create-index`: create index for PostGIS columns on the `$RESOURCE_ID` table.
    ```bash
    ckan spatialdata create-index $RESOURCE_ID -c $CONFIG_FILE
    ```

3. `populate-columns`: populate the PostGIS columns from the given lat & long fields. Equivalent to
   the `update_geom_columns()` action.
    ```bash
    ckan spatialdata populate-columns $RESOURCE_ID -l $LATITUDE_COLUMN -g $LONGITUDE_COLUMN -c $CONFIG_FILE
    ```

## Testing

_tests coming soon_

## Acknowledgements

Based on [ckanext-spatialdata](https://github.com/NaturalHistoryMuseum/ckanext-spatialdata) created by the Natural
History Museum in London, UK.
<img src=".github/nhm-logo.svg" align="left" width="150px" height="100px" hspace="40"/>

