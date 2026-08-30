# encoding: utf-8
import datetime
import logging
from typing import Optional

from ckan.plugins import toolkit
from ckan.types import DataDict
from ckanext.datastore import backend as datastore_db
from ckanext.datastore.helpers import is_single_statement

from ckanext.spatialdata.config import config
from ckanext.spatialdata.lib.constants import WKB_FIELD_NAME
from ckanext.spatialdata.lib.db import (
    create_geom_column,
    create_index,
    fields_exist,
    get_connection,
    Connection,
    index_exists,
    invoke_search_plugins,
    get_field_values,
)
from ckanext.spatialdata.lib.types import (
    StatusCallback,
    SpecificStatusCallback,
    GeoreferenceStatus,
)
from ckanext.spatialdata.lib.util import DEFAULT_CONTEXT, get_common_geom_type

logger = logging.getLogger(__name__)

GEOM_FIELD = toolkit.config.get("postgis.field", "_geom")
GEOM_MERCATOR_FIELD = toolkit.config.get("postgis.mercator_field", "_geom_webmercator")


BATCH_SIZE = 5000


def has_postgis_columns(
    resource_id: str,
    connection: Optional[Connection] = None,
) -> bool:
    """Returns TRUE if the given resource already has postgis columns

    The name of the columns is read from the configuration.

    :param resource_id: Resource to test
    :param connection: Database connection. If None, one will be
        created for this operation. (Default value = None)
    :returns: s: True if the resource database table already has postgis
              columns, False otherwise.

    """
    with get_connection(connection) as c:
        return fields_exist(c, resource_id, [GEOM_FIELD, GEOM_MERCATOR_FIELD])


def has_postgis_index(resource_id: str, connection: Optional[Connection] = None):
    """Returns TRUE if the given resource already has an index on postgis columns

    :param resource_id: The resource to test
    :param connection: Database connection. If None, one will be
        created for this operation. (Default value = None)
    :returns: True if the resource database already has the index for the
              postgis columns
    """
    with get_connection(connection) as c:
        return (
            has_postgis_columns(resource_id, c)
            and index_exists(c, resource_id, GEOM_FIELD)
            and index_exists(c, resource_id, GEOM_MERCATOR_FIELD)
        )


def create_postgis_columns(
    resource_id: str, geom_type: str, connection: Optional[Connection] = None
):
    """Create the PostGIS columns

    The column names are read from the configuration

    :param resource_id: The resource id to create the columns on
    :param geom_type: The type of geometry being created.
    :param connection: Database connection. If None, one will be
        created for this operation. (Default value = None)
    """
    c: Connection
    with get_connection(connection, write=True) as c:
        create_geom_column(c, resource_id, GEOM_FIELD, geom_type, 4326)
        create_geom_column(c, resource_id, GEOM_MERCATOR_FIELD, geom_type, 3857)


def create_postgis_index(resource_id: str, connection: Optional[Connection] = None):
    """Create geospatial index

    The column name to create the index on is read from the configuration

    :param resource_id: The resource to create the index on
    :param connection: Database connection. If None, one will be
        created for this operation. (Default value = None)
    """
    c: Connection
    with get_connection(connection, write=True) as c:
        if not has_postgis_index(resource_id, c):
            create_index(c, resource_id, GEOM_FIELD)
            create_index(c, resource_id, GEOM_MERCATOR_FIELD)


def populate_postgis_columns(
    resource_id: str,
    lat_field: str = None,
    lng_field: str = None,
    wkb_field: str = None,
    wkt_field: str = None,
    geom_type: str = "",
    connection: Optional[Connection] = None,
    status_callback: StatusCallback = lambda s, v, e: None,
):
    """Populate the PostGis columns from the give lat & long fields

    :param resource_id: The resource to populate
    :param lat_field: The latitude field to populate from
    :param lng_field: The longitude field to populate from
    :param wkt_field: The Well-Known Text field to populate from
    :param wkb_field: The Well-Known Binary field to populate from
    :param geom_type: Geometry type to be used in geom columns.
    :param connection: Database connection. If None, one will be
        created for this operation. (Default value = None)
    :param status_callback: Callable that logs status to CKAN task table
    """
    if lat_field and lng_field:
        _populate_columns_with_lat_lng(
            resource_id,
            lat_field,
            lng_field,
            connection=connection,
            status_callback=status_callback,
        )
    elif wkt_field:
        _populate_columns_with_wkt(
            resource_id,
            wkt_field,
            connection=connection,
            status_callback=status_callback,
            geom_type=geom_type,
        )
    elif wkb_field:
        _populate_columns_with_wkb(
            resource_id,
            wkb_field,
            connection=connection,
            status_callback=status_callback,
            geom_type=geom_type,
        )


def _populate_columns_with_lat_lng(
    resource_id: str,
    lat_field: str,
    lng_field: str,
    connection=None,
    status_callback: StatusCallback = lambda s, v, e: None,
):
    def _status_callback(value):
        status_callback(
            GeoreferenceStatus.WORKING,
            value={
                "notes": "Populating geom columns using Latitude and Longitude.",
                **value,
            },
        )

    source_sql = _get_rows_to_update_sql(
        resource_id, latitude_field=lat_field, longitude_field=lng_field
    )
    geom_update_sql = f"""
            UPDATE "{resource_id}"
            SET "{GEOM_FIELD}" = st_setsrid(st_makepoint("{lng_field}"::float8, "{lat_field}"::float8), 4326)
            WHERE _id = %s
         """
    geom_webmercator_update_sql = f"""
            UPDATE "{resource_id}" 
            SET "{GEOM_MERCATOR_FIELD}" = st_transform("{GEOM_FIELD}", 3857)
            WHERE {GEOM_FIELD} IS NOT NULL 
              AND _id = %s
        """

    _populate_columns_in_batches(
        source_sql,
        geom_update_sql,
        geom_webmercator_update_sql,
        connection=connection,
        status_callback=_status_callback,
    )


def _populate_columns_with_wkt(
    resource_id: str,
    wkt_field: str = None,
    connection=None,
    status_callback: StatusCallback = lambda s, v, e: None,
    geom_type: str = "",
):
    def _status_callback(value):
        status_callback(
            GeoreferenceStatus.WORKING,
            value={
                "notes": "Populating geom columns using Well-Known Text.",
                **value,
            },
        )

    set_geom = f'st_force2d(st_geomfromtext("{wkt_field}", 4326))'
    if "multi" in geom_type.lower():
        set_geom = f'st_multi(st_force2d(st_geomfromtext("{wkt_field}", 4326)))'

    source_sql = _get_rows_to_update_sql(resource_id, source_geom_field=wkt_field)
    geom_update_sql = f"""
        UPDATE "{resource_id}"
        SET "{GEOM_FIELD}" = {set_geom}
        WHERE _id = %s
    """
    geom_webmercator_update_sql = f"""
        UPDATE "{resource_id}"
        SET "{GEOM_MERCATOR_FIELD}" = st_transform("{GEOM_FIELD}", 3857)
        WHERE "{GEOM_FIELD}" IS NOT NULL 
          AND _id = %s
    """

    _populate_columns_in_batches(
        source_sql,
        geom_update_sql,
        geom_webmercator_update_sql,
        connection=connection,
        status_callback=_status_callback,
    )


def _populate_columns_with_wkb(
    resource_id: str,
    wkb_field: str = None,
    connection=None,
    status_callback: StatusCallback = lambda s, v, e: None,
    geom_type: str = "",
):
    def _status_callback(value):
        status_callback(
            GeoreferenceStatus.WORKING,
            value={
                "notes": "Populating geom columns using Well-Known Binary.",
                **value,
            },
        )

    set_geom = f'ST_Force2D(ST_GeomFromWKB("{wkb_field}", 4326))'
    if "multi" in geom_type.lower():
        set_geom = f'ST_Multi(ST_Force2D(ST_GeomFromWKB("{wkb_field}", 4326)))'

    source_sql = _get_rows_to_update_sql(resource_id, source_geom_field=wkb_field)

    geom_update_sql = f"""
        UPDATE "{resource_id}"
        SET "{GEOM_FIELD}" = {set_geom}
        WHERE _id = %s
    """
    geom_webmercator_update_sql = f"""
        UPDATE "{resource_id}"
        SET "{GEOM_MERCATOR_FIELD}" = st_transform("{GEOM_FIELD}", 3857)
        WHERE "{GEOM_FIELD}" IS NOT NULL 
          AND _id = %s
    """

    _populate_columns_in_batches(
        source_sql,
        geom_update_sql,
        geom_webmercator_update_sql,
        connection=connection,
        status_callback=_status_callback,
    )


def connect_and_get_field_values(resource_id: str, field: str, is_bytes: bool = False) -> list:
    c: Connection
    with get_connection() as c:
        values = get_field_values(c, resource_id, field, is_bytes=is_bytes)
        return values

def prep_table(
    resource,
    geom_type,
    status_callback: StatusCallback = lambda status: None,
):
    if not has_postgis_columns(resource["id"]):
        logger.info(f"Creating PostGIS columns for {resource['id']}.")
        status_callback(GeoreferenceStatus.WORKING, value={"notes": "Creating Columns"})
        create_postgis_columns(resource["id"], geom_type)

    if not has_postgis_index(resource["id"]):
        logger.info(f"Creating PostGIS indexes for {resource['id']}.")
        status_callback(
            GeoreferenceStatus.WORKING,
            value={"notes": "Indexing Geom Columns"},
        )
        create_postgis_index(resource["id"])


def prepare_and_populate_geoms(
    resource: dict,
    from_geojson_add: bool = False,
    status_callback: StatusCallback = lambda status, value, error: None,
) -> None:
    """Adds geometric data fields, geometric indexes and then populates the geometric fields based
    on extant data and spatialdata metadata.

    :param resource: CKAN Resource dict
    :param from_geojson_add: True if going from creation of new geojson file.
    """
    lat_field = resource.get("spatialdata_latitude_field")
    lng_field = resource.get("spatialdata_longitude_field")
    wkt_field = resource.get("spatialdata_wkt_field")

    # common args
    populate_args = {"resource_id": resource['id'], "status_callback": status_callback}

    # get format-specific args
    if lat_field and lng_field:
        populate_args["lat_field"] = lat_field
        populate_args["lng_field"] = lng_field
        geom_type = "POINT"
    elif from_geojson_add or wkt_field:
        if from_geojson_add:
            populate_args["wkb_field"] = WKB_FIELD_NAME
            values = connect_and_get_field_values(resource["id"], WKB_FIELD_NAME, is_bytes=True)
            geom_format = "wkb"
        else:
            populate_args["wkt_field"] = wkt_field
            values = connect_and_get_field_values(resource["id"], wkt_field)
            geom_format = "wkt"
        geom_type = get_common_geom_type(values, geom_format=geom_format)
    else:
        raise Exception(
            "If not uploading a geojson file, lat/long or wkt fields are required."
        )

    populate_args["geom_type"] = geom_type

    # add geom fields and indexes
    prep_table(resource, geom_type, status_callback=status_callback)

    # convert source data to postgis geometries
    logger.info(f"Populating PostGIS columns for {resource['id']}.")
    logger.debug(populate_args)
    populate_postgis_columns(**populate_args)

    # update metadata
    toolkit.get_action("resource_patch")(
        DEFAULT_CONTEXT,
        {
            "id": resource["id"],
            "spatialdata_last_geom_updated": datetime.datetime.now().isoformat(),
            "spatialdata_active": True,
            "spatialdata_status": "active",
        },
    )
    logger.info(f"Geometry columns for {resource['id']} populated.")


def _get_rows_to_update_sql(
    resource_id: str,
    latitude_field: str = None,
    longitude_field: str = None,
    source_geom_field: str = None,
) -> str:
    source_clause = ""
    if latitude_field and longitude_field:
        source_clause = (
            f'AND ("{latitude_field}" IS NOT NULL AND "{longitude_field}" IS NOT NULL)'
        )
    if source_geom_field:
        source_clause = f'AND "{source_geom_field}" IS NOT NULL'

    return f"""
          SELECT _id
          FROM "{resource_id}"
          WHERE ("{GEOM_FIELD}" IS NULL 
            OR "{GEOM_MERCATOR_FIELD}" IS NULL)
            {source_clause}
          ORDER BY _id
    """


def _populate_columns_in_batches(
    source_sql: str,
    geom_update_sql: str,
    geom_webmercator_update_sql: str,
    connection=None,
    status_callback: SpecificStatusCallback = lambda d: None,
):
    with get_connection(connection, write=True, raw=True) as c:
        read_cursor = c.cursor()
        write_cursor = c.cursor()

        read_cursor.execute(source_sql)

        count = 0
        incremental_commit_size = BATCH_SIZE

        while True:
            source_rows = read_cursor.fetchmany(incremental_commit_size)
            if not source_rows:
                break

            for row in source_rows:
                write_cursor.execute(geom_update_sql, (row[0],))
            c.commit()

            for row in source_rows:
                count += 1
                write_cursor.execute(geom_webmercator_update_sql, (row[0],))
            c.commit()

            logger.info(f"{count} rows geocoded.")
            status_callback({"rows_completed": count})
        c.commit()


def query_extent(data_dict: DataDict, connection: Optional[Connection] = None):
    """Return the spatial query extent of a datastore search

    :param data_dict: Dictionary defining the search
    :param connection:  (Default value = None)
    :returns: s a dictionary defining:
        {
            total_count: The total number of rows in the query,
            geom_count: The number of rows that have a geom,
            bounds: ((lat min, long min), (lat max, long max)) for the
                  queries rows
        }
    """
    r = toolkit.get_action("datastore_search")({}, data_dict)

    if "total" not in r or r["total"] == 0:
        return {"total_count": 0, "geom_count": 0, "bounds": None}

    result = {"total_count": r["total"], "bounds": None}

    field_types = dict([(f["id"], f["type"]) for f in r["fields"]])
    field_types["_id"] = "int"

    # Call plugin to obtain correct where statement
    (ts_query, where_clause, values) = invoke_search_plugins(data_dict, field_types)

    # Prepare and run our query
    query = """
        SELECT COUNT(r) AS count,
               ST_YMIN(ST_EXTENT(r)) AS ymin,
               ST_XMIN(ST_EXTENT(r)) AS xmin,
               ST_YMAX(ST_EXTENT(r)) AS ymax,
               ST_XMAX(ST_EXTENT(r)) AS xmax
        FROM   (
          SELECT "{geom_field}" AS r
          FROM   "{resource_id}" {ts_query}
          {where_clause}
        ) _tilemap_sub
    """.format(
        geom_field=config["postgis.field"],
        resource_id=data_dict["resource_id"],
        where_clause=where_clause,
        ts_query=ts_query,
    )

    if not is_single_statement(query):
        raise datastore_db.DatastoreException(
            {"query": ["Query is not a single statement."]}
        )

    with get_connection(connection) as c:
        query_result = c.execute(query, values)
        r = query_result.fetchone()

    result["geom_count"] = r["count"]
    if result["geom_count"] > 0:
        result["bounds"] = ((r["ymin"], r["xmin"]), (r["ymax"], r["xmax"]))
    return result

