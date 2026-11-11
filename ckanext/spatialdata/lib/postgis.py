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
    get_geom_column_type,
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
from ckanext.spatialdata.lib.util import (
    get_common_geom_type,
    has_geom_link,
    parse_geom_link,
    site_context,
)
from ckanext.datastore.backend.postgres import identifier

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
    source_srid: int = 4326,
):
    """Populate the PostGis columns from the give lat & long fields

    :param resource_id: The resource to populate
    :param lat_field: The latitude field to populate from
    :param lng_field: The longitude field to populate from
    :param wkt_field: The Well-Known Text field to populate from
    :param wkb_field: The Well-Known Binary field to populate from
    :param geom_type: Geometry type to be used in geom columns.
    :param source_srid: SRID of the WKB geometries; reprojected to 4326 if different.
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
            source_srid=source_srid,
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
    source_srid: int = 4326,
):
    def _status_callback(value):
        status_callback(
            GeoreferenceStatus.WORKING,
            value={
                "notes": "Populating geom columns using Well-Known Binary.",
                **value,
            },
        )

    source_srid = int(source_srid)
    source_geom = f'ST_GeomFromWKB("{wkb_field}", {source_srid})'
    if source_srid != 4326:
        source_geom = f"ST_Transform({source_geom}, 4326)"
    set_geom = f"ST_Force2D({source_geom})"
    if "multi" in geom_type.lower():
        set_geom = f"ST_Multi({set_geom})"

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
    source_srid: int = 4326,
) -> Optional[str]:
    """Adds geometric data fields, geometric indexes and then populates the geometric fields based
    on extant data and spatialdata metadata.

    :param resource: CKAN Resource dict
    :param from_geojson_add: True if going from creation of new geojson file.
    :returns: notes on the result for the job status, if any
    """
    notes = None
    if (
        not from_geojson_add
        and not _has_own_geom_fields(resource)
        and has_geom_link(resource)
    ):
        notes = prepare_and_populate_linked_geoms(
            resource, status_callback=status_callback
        )
    else:
        _prepare_and_populate_own_geoms(
            resource,
            from_geojson_add=from_geojson_add,
            status_callback=status_callback,
            source_srid=source_srid,
        )

    # update metadata
    toolkit.get_action("resource_patch")(
        site_context(),
        {
            "id": resource["id"],
            "spatialdata_last_geom_updated": datetime.datetime.now().isoformat(),
            "spatialdata_active": True,
            "spatialdata_status": "active",
        },
    )
    logger.info(f"Geometry columns for {resource['id']} populated.")
    return notes


def _has_own_geom_fields(resource: dict) -> bool:
    return bool(
        (
            resource.get("spatialdata_latitude_field")
            and resource.get("spatialdata_longitude_field")
        )
        or resource.get("spatialdata_wkt_field")
    )


def _prepare_and_populate_own_geoms(
    resource: dict,
    from_geojson_add: bool = False,
    status_callback: StatusCallback = lambda status, value, error: None,
    source_srid: int = 4326,
) -> None:
    """Populate the geom columns from the resource's own lat/lng, WKT or WKB."""
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
            populate_args["source_srid"] = source_srid
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


# Session-local table holding one geometry per link key; see
# prepare_and_populate_linked_geoms.
LINKED_GEOMS_TABLE = "spatialdata_linked_geoms"


def linked_geom_type(source_type: Optional[str], has_merged: bool) -> tuple[str, str]:
    """Geometry column type for linked geometries, and the SQL that fits a
    geometry to it.

    Unioning several geometries can turn e.g. polygons into a multipolygon,
    so when any keys were merged, single types are promoted to their multi
    type. Multi types are forced too, since a union of multipolygons that
    touch can come back as a single polygon.

    :param source_type: declared type of the geometry resource's geom column
    :param has_merged: True if any key had several geometries unioned
    :returns: ``(column type, SQL template with a {} for the geometry)``
    """
    source_type = (source_type or "GEOMETRY").upper()
    if source_type == "GEOMETRYCOLLECTION":
        return source_type, "ST_ForceCollection({})"
    if has_merged and source_type in ("POINT", "LINESTRING", "POLYGON"):
        source_type = "MULTI" + source_type
    if source_type.startswith("MULTI"):
        return source_type, "ST_Multi({})"
    return source_type, "{}"


def _link_key(table_alias: str, field: str) -> str:
    """SQL for a link key: compared as trimmed text, so a numeric id in one
    table still matches a text id in the other."""
    return f"btrim({table_alias}.{identifier(field)}::text)"


def linked_geoms_sql(geom_resource_id: str, geom_field: str) -> str:
    """SQL creating LINKED_GEOMS_TABLE: one geometry per key of the geometry
    resource, unioning the geometries of keys that appear more than once.

    Single geometries are copied as they are rather than run through
    ST_Union, which would be slow across a whole table and can reorder
    vertices.
    """
    key = _link_key("g", geom_field)
    table = identifier(geom_resource_id)
    geom = identifier(GEOM_FIELD)
    return f"""
        CREATE TEMP TABLE {LINKED_GEOMS_TABLE} AS
        WITH keyed AS (
            SELECT {key} AS key, g.{geom} AS geom
            FROM {table} g
            WHERE g.{geom} IS NOT NULL
              AND {key} <> ''
        ),
        counted AS (
            SELECT key, count(*) AS n FROM keyed GROUP BY key
        )
        SELECT k.key, k.geom, false AS merged
        FROM keyed k JOIN counted c USING (key)
        WHERE c.n = 1
        UNION ALL
        SELECT k.key, ST_Union(k.geom), true
        FROM keyed k JOIN counted c USING (key)
        WHERE c.n > 1
        GROUP BY k.key
    """


def linked_update_sql(resource_id: str, local_field: str, fit_geom: str) -> str:
    """SQL setting the geom columns of rows ``_id > %s AND _id <= %s`` from
    LINKED_GEOMS_TABLE.

    Every row in the range is written, so rows whose key no longer matches
    (or is empty) get NULL geometries instead of keeping stale ones.

    :param fit_geom: SQL template from linked_geom_type
    """
    table = identifier(resource_id)
    geom = fit_geom.format("l.geom")
    return f"""
        UPDATE {table} AS t
        SET {identifier(GEOM_FIELD)} = {geom},
            {identifier(GEOM_MERCATOR_FIELD)} = ST_Transform({geom}, 3857)
        FROM {table} AS src
        LEFT JOIN {LINKED_GEOMS_TABLE} l ON l.key = {_link_key("src", local_field)}
        WHERE t._id = src._id
          AND src._id > %s AND src._id <= %s
    """


def _count(n: int, noun: str) -> str:
    return f"{n:,} {noun}{'' if n == 1 else 's'}"


def _check_geom_link(resource: dict, local_field: str, geom_field: str) -> dict:
    """Check a linked resource can be georeferenced; return the geometry
    resource. Raises ValueError with a message for the job status if not."""
    geom_resource_id = resource["spatialdata_geom_resource"]
    if geom_resource_id == resource["id"]:
        raise ValueError("A resource can't take its geometries from itself.")
    try:
        geom_resource = toolkit.get_action("resource_show")(
            site_context(), {"id": geom_resource_id}
        )
    except toolkit.ObjectNotFound:
        raise ValueError(f"Geometry resource {geom_resource_id} does not exist.")
    if not geom_resource.get("datastore_active"):
        raise ValueError(
            f"Geometry resource {geom_resource_id} is not in the datastore."
        )
    if not has_postgis_columns(geom_resource["id"]):
        raise ValueError(
            f"Geometry resource {geom_resource_id} has not been georeferenced. "
            "Georeference it before this resource."
        )
    with get_connection() as c:
        if not fields_exist(c, resource["id"], [local_field]):
            raise ValueError(f'Field "{local_field}" is not in this resource.')
        if not fields_exist(c, geom_resource["id"], [geom_field]):
            raise ValueError(
                f'Field "{geom_field}" is not in geometry resource {geom_resource_id}.'
            )
    return geom_resource


def prepare_and_populate_linked_geoms(
    resource: dict,
    status_callback: StatusCallback = lambda status, value, error: None,
) -> str:
    """Populate a resource's geom columns from another, georeferenced
    resource, joining rows on ``spatialdata_geom_link``
    (``field_in_this_resource->field_in_geom_resource``).

    The geometries are copied, so the tile server and the rest of the
    extension treat the resource like any other. Rerun after the geometry
    resource changes to pick its changes up.

    :returns: notes for the job status, with how many rows matched
    """
    resource_id = resource["id"]
    local_field, geom_field = parse_geom_link(resource["spatialdata_geom_link"])
    geom_resource = _check_geom_link(resource, local_field, geom_field)

    def working(notes: str, **value):
        status_callback(GeoreferenceStatus.WORKING, value={"notes": notes, **value})

    with get_connection(write=True, raw=True) as c:
        cur = c.cursor()

        working("Collecting geometries from the linked resource.")
        cur.execute(f"DROP TABLE IF EXISTS {LINKED_GEOMS_TABLE}")
        cur.execute(linked_geoms_sql(geom_resource["id"], geom_field))
        cur.execute(f"CREATE INDEX ON {LINKED_GEOMS_TABLE} (key)")
        cur.execute(f"ANALYZE {LINKED_GEOMS_TABLE}")
        cur.execute(
            f"SELECT count(*), count(*) FILTER (WHERE merged) FROM {LINKED_GEOMS_TABLE}"
        )
        key_count, merged_count = cur.fetchone()
        # release the read lock on the geometry resource's table
        c.commit()
        if merged_count:
            logger.info(
                f"{merged_count} keys in {geom_resource['id']} have several "
                "geometries; they were unioned."
            )

        with get_connection() as read_c:
            source_type = get_geom_column_type(read_c, geom_resource["id"], GEOM_FIELD)
            existing_type = get_geom_column_type(read_c, resource_id, GEOM_FIELD)
        geom_type, fit_geom = linked_geom_type(source_type, bool(merged_count))
        if existing_type and existing_type not in (geom_type, "GEOMETRY"):
            raise ValueError(
                f"This resource's {GEOM_FIELD} column holds {existing_type} "
                f"geometries, but the linked geometries are {geom_type}. Drop "
                f'the "{GEOM_FIELD}" and "{GEOM_MERCATOR_FIELD}" columns and '
                "georeference again."
            )
        prep_table(resource, geom_type, status_callback=status_callback)

        cur.execute(f"SELECT min(_id), max(_id) FROM {identifier(resource_id)}")
        min_id, max_id = cur.fetchone()
        update_sql = linked_update_sql(resource_id, local_field, fit_geom)
        count = 0
        if min_id is not None:
            for start in range(min_id - 1, max_id, BATCH_SIZE):
                cur.execute(update_sql, (start, start + BATCH_SIZE))
                count += cur.rowcount
                c.commit()
                logger.info(f"{count} rows geocoded.")
                working(
                    "Populating geom columns from the linked resource.",
                    rows_completed=count,
                )

        cur.execute(
            f"""
            SELECT count(*),
                   count(*) FILTER (WHERE {identifier(GEOM_FIELD)} IS NOT NULL),
                   count(*) FILTER (WHERE {_link_key("t", local_field)} <> '')
            FROM {identifier(resource_id)} t
            """
        )
        total, matched, keyed = cur.fetchone()
        cur.execute(f"DROP TABLE IF EXISTS {LINKED_GEOMS_TABLE}")
        c.commit()

    notes = (
        f"{matched:,} of {_count(total, 'row')} matched a geometry in the linked "
        f"resource on {local_field}->{geom_field}."
    )
    if keyed < total:
        notes += f" {_count(total - keyed, 'row')} with no {local_field}."
    if merged_count:
        notes += (
            f" {merged_count:,} of the linked resource's {_count(key_count, 'key')} "
            "had several geometries, which were unioned."
        )
    logger.info(notes)
    return notes


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



def resource_extent(resource_id: str) -> Optional[list[float]]:
    """Bounding box of a georeferenced resource's geometries.

    Uses the planner statistics (``ST_EstimatedExtent``) when the table has
    been analyzed, which is instant but slightly generous; otherwise falls
    back to scanning the table with ``ST_Extent``.

    Each query gets its own connection, so a failed estimate can't abort
    the transaction the exact query runs in.

    :param resource_id: The resource (datastore table) to measure
    :returns: ``[xmin, ymin, xmax, ymax]`` in EPSG:4326, or None if the
        table has no geometries.
    """
    from sqlalchemy import text

    geom_field = config["postgis.field"]
    estimated = text(
        "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) "
        "FROM (SELECT ST_EstimatedExtent('public', :table, :column) AS e) s"
    )
    exact = text(
        f'SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) '
        f'FROM (SELECT ST_Extent("{geom_field}") AS e FROM "{resource_id}") s'
    )

    row = None
    try:
        with get_connection() as c:
            row = c.execute(
                estimated, {"table": resource_id, "column": geom_field}
            ).fetchone()
    except Exception:
        # no statistics yet, or an older PostGIS that raises instead of
        # returning NULL
        row = None

    if not row or row[0] is None:
        with get_connection() as c:
            row = c.execute(exact).fetchone()

    if not row or row[0] is None:
        return None
    return [float(v) for v in row]
