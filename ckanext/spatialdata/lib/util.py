# encoding: utf-8
import logging
import os
from pathlib import Path

from ckan.plugins import toolkit
from ckanext.datastore.backend.postgres import identifier
from geomet import wkt, wkb

from ckanext.spatialdata.lib.db import get_connection


def site_context() -> dict:
    """A fresh context acting as the CKAN site user (a sysadmin).

    Used by background jobs and internal calls. The site user's name is
    ``ckan.site_id``, which differs between environments, so it's looked up
    rather than hard-coded.
    """
    site_user = toolkit.get_action("get_site_user")({"ignore_auth": True}, {})
    return {"user": site_user["name"]}


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
    return resource["datastore_active"] and has_geometry_source(resource)


def out_of_sync(resource: dict):
    return (
        not resource.get("spatialdata_last_geom_updated")
        or resource.get("spatialdata_last_geom_updated") < resource.get("last_modified")
        or resource.get("spatialdata_last_geom_updated")
        < resource.get("metadata_modified")
    )


def has_geometry_source(resource: dict):
    return bool(
        (
            resource.get("spatialdata_latitude_field")
            and resource.get("spatialdata_longitude_field")
        )
        or resource.get("spatialdata_wkt_field")
        or has_geom_link(resource)
    )


GEOM_LINK_SEPARATOR = "->"


def parse_geom_link(value: str) -> tuple[str, str]:
    """Split a ``spatialdata_geom_link`` value into its two field names.

    The link has the form ``field_in_this_resource->field_in_geom_resource``,
    e.g. ``PARID->PIN``. Whitespace around either name is ignored.

    :raises ValueError: if the value isn't of that form
    """
    parts = (value or "").split(GEOM_LINK_SEPARATOR)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ValueError(
            "Must be of the form field_in_this_resource->field_in_geom_resource "
            "(e.g. PARID->PIN)."
        )
    return parts[0].strip(), parts[1].strip()


def has_geom_link(resource: dict) -> bool:
    """True if the resource takes its geometries from another resource."""
    return bool(
        resource.get("spatialdata_geom_resource")
        and resource.get("spatialdata_geom_link")
    )


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
