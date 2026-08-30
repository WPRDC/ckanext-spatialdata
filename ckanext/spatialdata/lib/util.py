# encoding: utf-8
import logging
import os
from pathlib import Path

from ckan.plugins import toolkit
from ckanext.datastore.backend.postgres import identifier
from geomet import wkt, wkb

from ckanext.spatialdata.lib.db import get_connection

DEFAULT_CONTEXT = {"user": "default"}

from ckan.model import parse_db_config


import ckanext.spatialdata as spatialdata_module


logger = logging.getLogger(__name__)


def load_wkb(wkb_data: bytes | str):
    data = wkb_data
    if type(wkb_data) == str:
        data = bytes.fromhex(wkb_data[2:])
    return wkb.loads(data)

def dump_wkb(geojson: dict):
    return wkb.dumps(geojson)


def load_wkt(wkt_data: str):
    return wkt.loads(wkt_data)

def dump_wkt(geojson: dict):
    return wkt.dumps(geojson)


def get_common_geom_type(values: list[str | bytes], geom_format="wkt") -> str:
    """Finds the common geometry type from a list of WKT geometries.

    If only one type is present, it is returned.

    When a single type and its collection type are present, the collection type
        is returned as it supports both.
        (e.g. if "Point" and "Multipoint" are present, it returns "MULTIPOINT")

    If incompatible types are present, "GEOMETRYCOLLECTION" is returned.

    :returns: the common geometry type name in all caps
    """
    load = load_wkb if geom_format == "wkb" else load_wkt
    geom_types = list(
        set(
            [
                load(value)["type"].upper()
                for value in values
                if value is not None
            ]
        )
    )

    if not geom_types:
        raise TypeError(f"At least one {geom_format.upper()} value must be provided.")
    if len(geom_types) == 1:
        return geom_types[0]
    if len(geom_types) > 2:
        return "GEOMETRYCOLLECTION"

    ordered_types: list[str] = sorted(geom_types, key=lambda x: len(x))
    if ordered_types[0] in ordered_types[1]:
        return ordered_types[1].upper()

    return "GEOMETRYCOLLECTION"


def get_resource_file_path(resource_id: str) -> Path:
    value = (
        Path(toolkit.config.get("ckan.storage_path"))
        / "resources"
        / resource_id[:3]
        / resource_id[3:6]
        / resource_id[6:]
    )
    return value


def should_be_updated(resource: dict):
    return can_be_spatial(resource) and out_of_sync(resource)


def can_be_spatial(resource: dict):
    return resource["datastore_active"] and _has_necessary_metadata(resource)


def out_of_sync(resource: dict):
    return (
        not resource.get("spatialdata_last_geom_updated")
        or resource.get("spatialdata_last_geom_updated") < resource.get("last_modified")
        or resource.get("spatialdata_last_geom_updated")
        < resource.get("metadata_modified")
    )


def _has_necessary_metadata(resource: dict):
    return (
        resource.get("spatialdata_latitude_field")
        and resource.get("spatialdata_longitude_field")
    ) or resource.get("spatialdata_wkt_field")


def update_fulltext_trigger():
    parsed_db = parse_db_config("ckan.datastore.write_url")

    datastore_db = parsed_db["db_name"]
    write_user = parsed_db["db_user"]

    template_filename = os.path.join(
        os.path.dirname(spatialdata_module.__file__), "update_triggers.sql"
    )
    with open(template_filename) as fp:
        template = fp.read()
    sql = template.format(
        datastoredb=identifier(datastore_db),
        writeuser=identifier(write_user),
    ).replace("%", "%%")
    logger.debug(sql)

    with get_connection(write=True) as conn:
        results = conn.execute(sql)
    logger.debug(results)
