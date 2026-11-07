# encoding: utf-8
import json
import logging
import re
from typing import Any, Union, Iterable

import geojson
from ckan.logic import NotFound
from ckan.plugins import toolkit
from geomet import wkb

from ckanext.spatialdata.lib.constants import WKB_FIELD_NAME
from ckanext.spatialdata.lib.postgis import prepare_and_populate_geoms
from ckanext.spatialdata.lib.types import StatusCallback, GeoreferenceStatus
from ckanext.spatialdata.lib.util import get_resource_file_path, site_context

logger = logging.getLogger(__name__)


def validate_sub_geoms(geom_type, sub_geom_type, coords):
    """
    Validates set of geometries returning only the valid ones
    """
    valid_sub_coords = []
    for sub_coords in coords:
        sub_geom = sub_geom_type(sub_coords)
        if sub_geom.is_valid:
            valid_sub_coords.append(sub_coords)

    if valid_sub_coords:
        # build from the valid parts only, so one bad part doesn't drop the
        # whole collection
        return geom_type(valid_sub_coords)
    return None


def validate_geojson_geom(geojson_geo: dict) -> dict | None:
    """Validates a GeoJSON geometry.
    Returns the geometry if valid, otherwise returns None
    """
    geo_type = geojson_geo.get("type").lower()

    # load geom into geojson library geometry
    data = None
    coords = geojson_geo.get("coordinates")
    if geo_type == "point":
        data = geojson.Point(coords)
    elif geo_type == "linestring":
        data = geojson.LineString(coords)
    elif geo_type == "polygon":
        data = geojson.Polygon(coords)

    # for collections, build them from validated child geoms
    elif geo_type == "multipoint":
        data = validate_sub_geoms(geojson.MultiPoint, geojson.Point, coords)
    elif geo_type == "multilinestring":
        data = validate_sub_geoms(geojson.MultiLineString, geojson.LineString, coords)
    elif geo_type == "multipolygon":
        data = validate_sub_geoms(geojson.MultiPolygon, geojson.Polygon, coords)

    if data and data.is_valid:
        return data
    return None


def geojson2wkb(geojson_geo: dict) -> bytes | None:
    geo_data = validate_geojson_geom(geojson_geo)
    try:
        if geo_data:
            return wkb.dumps(geo_data)
        else:
            return None
    except Exception as e:
        logger.warning(e)
        return None


def to_row(feature: dict, fields: Iterable[dict]) -> dict:
    row = {}
    # transfer available fields
    for field in fields:
        row[field] = feature["properties"].get(field, None)
    row[WKB_FIELD_NAME] = geojson2wkb(feature["geometry"])
    return row


def geojson_srid(geojson_obj: dict) -> int:
    """SRID declared by a GeoJSON object's legacy ``crs`` member.

    RFC 7946 GeoJSON has no ``crs`` member and is always WGS84 (EPSG:4326),
    but files exported from ArcGIS/QGIS often still declare one, e.g.
    ``{"type": "name", "properties": {"name": "EPSG:2272"}}``.
    """
    crs = geojson_obj.get("crs")
    if not crs:
        return 4326
    name = str((crs.get("properties") or {}).get("name", ""))
    if re.search(r"CRS84$", name, re.IGNORECASE):
        return 4326
    match = re.search(r"EPSG:+(?:[\d.]*:)?(\d+)$", name, re.IGNORECASE)
    if not match:
        raise ValueError(f"Unsupported GeoJSON crs: {crs!r}")
    return int(match.group(1))


def load_geojson_to_datastore(
    resource_id: str,
    aliases: Union[list[str], str] = None,
    indexes: list[str] = None,
    status_callback: StatusCallback = lambda d: None,
):
    """Converts geojson to tabular format and loads in to the datastore"""
    resource: dict = toolkit.get_action("resource_show")(
        site_context(), {"id": resource_id}
    )
    # validate
    if not resource or not resource["id"]:
        toolkit.ValidationError("Resource not found.")
    if resource["format"].lower() != "geojson":
        toolkit.ValidationError("Only GeoJSON is supported at the moment.")

    # load geojson data and convert to list of dicts
    geojson_filepath = get_resource_file_path(resource_id)
    with open(geojson_filepath) as f:
        logger.info(f"Loading geojson from {geojson_filepath}.")
        geojson: dict = json.load(f)

    source_srid = geojson_srid(geojson)
    if source_srid != 4326:
        logger.info(
            f"GeoJSON for {resource_id} is in EPSG:{source_srid}; reprojecting to EPSG:4326."
        )

    # find the full set of keys
    source_fields = set()
    for feature in geojson["features"]:
        source_fields |= set(feature["properties"].keys())

    # records for datastore_create
    records: list[dict[str, Any]] = [
        to_row(feature, source_fields)
        for feature in geojson["features"]
        if feature["geometry"]
    ]
    invalid_count = sum(1 for r in records if r[WKB_FIELD_NAME] is None)
    if invalid_count:
        logger.warning(
            f"{invalid_count} of {len(records)} features in {resource_id} have "
            f"invalid geometries; they are loaded without a geometry."
        )

    fields = resource.get("spatialdata_fields_definition")
    if not fields:
        fields = [
            {"id": k, "type": "bytea" if k == WKB_FIELD_NAME else "text"}
            for k in records[0].keys()
        ]

    logger.debug(fields)

    # delete datastore table if it exists
    try:
        toolkit.get_action("datastore_info")(site_context(), {"id": resource_id})
        logger.info(f"DELETING {resource_id}")
        toolkit.get_action("datastore_delete")(
            site_context(), {"resource_id": resource_id, "force": True}
        )
    except NotFound:
        pass

    # create table in datastore
    create_options: dict = {
        "resource_id": resource_id,
        "aliases": aliases,
        "records": records,
        "fields": fields,
        "force": True,
    }
    if indexes:
        create_options["indexes"] = indexes
    logger.debug(create_options["fields"])
    status_callback(
        GeoreferenceStatus.WORKING,
        value={"notes": f"Creating datastore table for {resource_id}"},
    )
    toolkit.get_action("datastore_create")(site_context(), create_options)

    prepare_and_populate_geoms(
        resource,
        from_geojson_add=True,
        source_srid=source_srid,
        status_callback=status_callback,
    )
