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
curl -X GET https://data.wprdc.org/api/action/spatialdata_status?resource_id=<RESOURCE_ID>
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

