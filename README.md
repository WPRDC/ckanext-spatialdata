[![CKAN](https://img.shields.io/badge/ckan-2.12-orange.svg?style=flat-square)](https://github.com/ckan/ckan)

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
| `spatialdata.tileserver_url`          | Public base URL of the tile server, used by the Map view and the TileJSON links in the dataset page's "Mappable" modal. Empty turns both off. See [Tile server](#tile-server). | _(empty)_ |
| `spatialdata.tile_source_id_format`   | Tile source id pattern; must match `source_id_format` for the datastore connection in Martin's config. Placeholders: `{table}`, `{column}`, `{schema}`. | table.{table}.{column} |
| `spatialdata.tile_function_source`    | Martin source id of the Map view's tile function. Must match the function `source_id_format` in Martin's config. See [Map view tiles](#map-view-tiles). | public.spatialdata_tiles |
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

### Tile server

The Map view and the vector-tile links in the dataset page's "Mappable" modal need a tile
server that publishes the datastore's PostGIS tables. The extension is built around
[Martin](https://maplibre.org/martin/), but any server that serves TileJSON per table will do.

1. Run Martin against the **datastore** database (not the CKAN database), auto-publishing its
   tables, with a source id format that includes the table and geometry column. A minimal
   `config.yaml`:

    ```yaml
    cors: true            # or add CORS headers in a proxy in front of Martin; not both
    postgres:
      - connection_string: postgresql://<read-only user>:<password>@<host>/datastore
        default_srid: 4326
        auto_publish:
          from_schemas: [public]
          tables:
            source_id_format: 'table.{table}.{column}'
          functions:
            source_id_format: '{schema}.{function}'
    ```

   Each georeferenced resource is then served at `<martin url>/table.<resource id>._geom`
   (TileJSON), with tiles under `.../{z}/{x}/{y}`. Martin discovers tables when it starts,
   so if a newly georeferenced resource's TileJSON returns 404, restart Martin.

2. Point CKAN at it:

    ```ini
    spatialdata.tileserver_url = https://tiles.example.org
    # only if you changed source_id_format above
    spatialdata.tile_source_id_format = table.{table}.{column}
    # if Martin's minzoom is set, so the map can ask users to zoom in below it
    spatialdata.tile_minzoom = 9
    ```

3. Make sure browsers can reach it. The map loads TileJSON and tiles straight from
   `spatialdata.tileserver_url`, so it must be a public URL, and responses must carry
   `Access-Control-Allow-Origin` for the CKAN site. Enable CORS in Martin **or** in the proxy
   in front of it; if both add the header, browsers reject the tiles.

4. Install the Map view's tile function (below) and restart Martin.

To check it, open the TileJSON URL from a georeferenced resource's entry in the "Mappable"
modal; it should return JSON with a `tiles` array.

#### Map view tiles

Table sources carry every column of every row, so tiles of large tables get huge (a z12
tile of a ~1M row table was over 200 MB). The Map view instead uses a PostGIS function,
`public.spatialdata_tiles` ([tile_function.sql](ckanext/spatialdata/tile_function.sql)),
which Martin publishes as a function source:

```
<martin url>/public.spatialdata_tiles/{z}/{x}/{y}?resource=<resource id>&fields=a,b
```

- Tiles hold only `_id` and the requested columns: the view's hover fields, its popup
  title field, and any column its style reads. Names that aren't columns are ignored.
- Below zoom 16, points are thinned to one per 2-pixel cell (keeping the newest row), since
  closer points overlap on the map anyway.
- Any georeferenced table is served without restarting Martin. Tile URLs carry the
  resource's `spatialdata_last_geom_updated`, so georeferencing again bypasses cached tiles.

Install or update it in the datastore database, then restart Martin the first time so it
publishes the function:

```bash
ckan spatialdata-init-tiles -c $CONFIG_FILE
```

The `ckan-docker` image runs this at every start (`docker-entrypoint.d/20_spatialdata_tiles.sh`).
The "Mappable" modal's TileJSON links still use the table sources, with every column.

## Map view

The plugin provides a `spatialdata_view` resource view ("Map") that draws a georeferenced
resource with [MapLibre GL JS](https://maplibre.org/), using the resource's vector tiles
from the tile server. Points, lines and polygons are all drawn. Hovering over a feature
shows a summary from the tiles; clicking it loads the whole row.

- It is offered for resources with `spatialdata_active` set, and only when
  `spatialdata.tileserver_url` is configured.
- A Map view is added automatically when a georeferencing job completes. For resources
  georeferenced before this existed, add it from the resource's "Views" tab, or run
  `ckan views create spatialdata_view`.
- The browser loads tiles straight from the tile server, so the tile server must send CORS
  headers that allow the CKAN site's origin. See [Tile server](#tile-server).

### Popups

Each Map view has popup settings, under **Popups** in the view's settings:

| Setting            | Description |
|--------------------|-------------|
| `popup_title_field` | Field shown as the heading of hover and click popups. |
| `hover_fields`      | Fields shown on hover, picked from the resource's datastore columns (stored as `STATUS,CREATED_ON`). Only these (plus the title field and any the style uses) are sent to the map, so keep the list short for large tables. |
| `popup_template`    | Shown on click: Markdown with `{{ field }}` for a field's value. Empty lists every field. |

A click template for 311 requests might be:

```markdown
Status: **{{ STATUS }}**, opened {{ CREATED_ON }}

{{ ADDRESS }} ({{ NEIGHBORHOOD }})
```

Clicking fetches `/dataset/<id>/resource/<resource id>/spatialdata/feature/<_id>?view=<view id>`,
which reads the row with `datastore_search` as the viewer and renders it with that view's
saved template. Field values are escaped, so data can't add formatting or links, and the
rendered Markdown is sanitized like other CKAN Markdown. While editing a view, the preview's
hover popups follow the unsaved settings, but clicks use the saved template.

### Map style

Each Map view has a **Map style** setting: a JSON list of
[MapLibre layers](https://maplibre.org/maplibre-style-spec/layers/) drawn from the resource,
bottom to top. Leave out `id`, `source` and `source-layer`; the view fills them in, so a style
can only draw the view's own resource. Layer types: `fill`, `line`, `circle`, `symbol`,
`heatmap` and `fill-extrusion`. When no style is set, the default in `lib/map_style.py` is
used: one fill, line and circle layer, so any geometry type renders.

Style by a column with expressions such as `["get", "column"]`; columns read with `get` or
`has` are added to the view's tiles automatically. For example, to color polygons by a `ZONE`
column and outline them:

```json
[
  {
    "type": "fill",
    "paint": {
      "fill-color": ["match", ["get", "ZONE"], "R1", "#4c9f70", "C1", "#e4572e", "#888888"],
      "fill-opacity": 0.5
    }
  },
  {"type": "line", "paint": {"line-color": "#222222", "line-width": 1}}
]
```

The style is edited on the view's settings page in a code editor with JSON highlighting.
It is checked as you type with MapLibre's style validator: problems are listed by layer,
and the view can't be saved until they are fixed. Preview shows the result on the map
before saving. "Reset to default" puts back the default style.

A style can also be set through the API, as a JSON string in the view's `style` field:

```shell
curl -X POST https://data.wprdc.org/api/3/action/resource_view_patch \
   -H 'Content-Type: application/json' \
   -H 'Authorization: <API_TOKEN>' \
   -d '{"id": "<VIEW_ID>", "style": "[{\"type\": \"circle\", \"paint\": {\"circle-color\": \"#e4572e\"}}]"}'
```

The server checks the JSON, the list shape and the layer types, but not paint or layout
values; those are only checked in the editor. A style set through the API with a bad value
still saves, and the map shows the problem as a style error. Setting a style identical to
the default clears it, so the view keeps following the default.

### Vendored libraries

| Library | Version | Path | Used by |
|---------|---------|------|---------|
| [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) (BSD-3-Clause) | 5.6.0 | `assets/vendor/maplibre-gl` | the map |
| [CodeMirror](https://codemirror.net/5/) (MIT) | 5.65.18 | `assets/vendor/codemirror` | the style editor |
| [maplibre-gl-style-spec](https://github.com/maplibre/maplibre-style-spec) (BSD-3-Clause) | 23.3.0 | `assets/vendor/maplibre-gl-style-spec` | style validation in the editor; keep it on the version MapLibre GL JS depends on |

## Usage

### Geospatial metadata

GeoJSON files can be parsed without any extra metadata.

To parse tabular files, you must update the resources extra fields.

The file can't be parsed unless either `spatialdata_longitude_field` AND `spatialdata_latitude_field` are provided,
OR `spatialdata_wkt_field` is provided, OR the resource is linked to another resource's geometries (below).

#### Writable Fields

| Field                         | Description                                                                                                                                                                                                                            |
|-------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| spatialdata_longitude_field   | Name of field that contains longitude data                                                                                                                                                                                             | 
| spatialdata_latitude_field    | Name of field that contains latitude data                                                                                                                                                                                              | 
| spatialdata_wkt_field         | Name of field that contains Well-Known Text data                                                                                                                                                                                       | 
| spatialdata_geom_resource     | ID of a georeferenced resource to take geometries from. Used with `spatialdata_geom_link`.                                                                                                                                            |
| spatialdata_geom_link         | How rows join the geometry resource: `field_in_this_resource->field_in_geom_resource`, e.g. `PARID->PIN`.                                                                                                                              |
| spatialdata_fields_definition | **_Optional_**, **_Only used with GeoJSON resources._** Must be a valid [Fields](https://docs.ckan.org/en/2.10/maintaining/datastore.html#fields) json object. Used to provide field types when loading a GeoJSON into the datastore.' |

#### Geometries from another resource

A table with no geometry of its own can borrow one from another resource that has been georeferenced. For example,
property assessments can be mapped by joining their parcel ids to a parcel boundary resource:

```
spatialdata_geom_resource = <parcel boundaries resource id>
spatialdata_geom_link     = PARID->PIN
```

Georeferencing copies the matching geometry into this resource's own geometry columns, so the tile server and Map view
treat it like any other georeferenced resource.

- Keys are compared as text with surrounding whitespace trimmed, so a numeric id still matches a text one.
- If a key appears more than once in the geometry resource, those geometries are combined with `ST_Union`. Single
  geometry types are then promoted to their multi type (e.g. `POLYGON` to `MULTIPOLYGON`).
- Rows with no match get empty geometries. The job's status notes report how many rows matched.
- The geometry resource must be georeferenced first. `spatialdata_submit_package` queues linked resources last, but
  with several workers, georeference the geometry resource before submitting resources that link to it.
- The geometries are a copy. Georeference this resource again after the geometry resource changes.
- If a resource also has its own latitude/longitude or WKT fields, those are used and the link is ignored.

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

#### `spatialdata-init-tiles`

Create or replace the Map view's tile function in the datastore database. See
[Map view tiles](#map-view-tiles).

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

The tests in `ckanext/spatialdata/tests` are unit tests: they cover the map view and its
style handling, the template helpers, geometry validation and the validators, and need no
datastore, Solr or Redis. CKAN still needs an initialised (empty) database to start, so use a
dedicated test database, never one with real data. `conftest.py` blocks CKAN's
database-resetting fixtures (`clean_db`, `reset_db` and others) as a further guard.

In the ckan-docker dev container (`ckan_test` is created by the Postgres init scripts):

```bash
docker compose -f docker-compose.dev.yml exec -w /srv/app/src_extensions/ckanext-spatialdata ckan-dev sh -c '
  export CKAN_SQLALCHEMY_URL="${CKAN_SQLALCHEMY_URL%/*}/ckan_test"
  ckan -c test.ini db init     # once, or after CKAN upgrades
  pytest --ckan-ini=test.ini ckanext/spatialdata/tests'
```

Elsewhere, point `use = config:...` in `test.ini` at your CKAN checkout's `test-core.ini` and
set `sqlalchemy.url` (or `CKAN_SQLALCHEMY_URL`) to a test database.

## Acknowledgements

Based on [ckanext-spatialdata](https://github.com/NaturalHistoryMuseum/ckanext-spatialdata) created by the Natural
History Museum in London, UK.
<img src=".github/nhm-logo.svg" align="left" width="150px" height="100px" hspace="40"/>

