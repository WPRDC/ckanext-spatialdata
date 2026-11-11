# encoding: utf-8
"""Map view tiles: a Martin function source that includes only chosen columns.

Table sources (``table.<id>._geom``) carry every column, which makes tiles of
big tables huge: a z12 tile of a ~1M row table was over 200 MB. The map view
instead uses ``spatialdata_tiles`` (see tile_function.sql), asking only for
the columns the view shows on hover or styles by. The full row is fetched when a
feature is clicked.
"""
import logging
import os
from typing import Any, Iterable, Optional
from urllib.parse import urlencode

from ckanext.spatialdata.config import config

logger = logging.getLogger(__name__)

# Layer name inside the function's tiles.
TILE_LAYER = "features"

# Columns never sent in tiles or shown in popups.
INTERNAL_FIELDS = ("_full_text", "spatialdata_wkb")

FIELD_LIST_SEPARATOR = ","


def tile_function_sql() -> str:
    from ckanext.spatialdata.lib.postgis import GEOM_FIELD, GEOM_MERCATOR_FIELD

    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tile_function.sql")
    with open(path) as fp:
        template = fp.read()
    # plain replacement: the SQL has other braces (e.g. {z}/{x}/{y})
    for name, value in (
        ("layer", TILE_LAYER),
        ("geom_field", GEOM_FIELD),
        ("mercator_field", GEOM_MERCATOR_FIELD),
    ):
        template = template.replace("{" + name + "}", value)
    return template


def install_tile_function() -> None:
    """Create or replace the tile function in the datastore database.

    Martin only finds functions when it starts, so restart it after the
    first install.
    """
    from ckanext.spatialdata.lib.db import get_connection

    # raw connection: the SQL is full of % and : that a driver would treat
    # as parameters
    with get_connection(write=True, raw=True) as c:
        c.cursor().execute(tile_function_sql())
        c.commit()


def parse_field_list(value: Any) -> list[str]:
    """Field names from a comma-separated string (or a list), trimmed,
    without blanks or repeats, in order."""
    if not value:
        return []
    if isinstance(value, str):
        value = value.split(FIELD_LIST_SEPARATOR)
    fields: list[str] = []
    for name in value:
        name = str(name).strip()
        if name and name not in fields:
            fields.append(name)
    return fields


def style_fields(layers: Iterable[dict]) -> list[str]:
    """Columns a map style reads with ``["get", "column"]`` (or ``has``), so
    they can be added to the tiles."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            if (
                len(node) == 2
                and node[0] in ("get", "has")
                and isinstance(node[1], str)
                and node[1] not in found
            ):
                found.append(node[1])
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)

    walk(list(layers))
    return found


def tile_fields(view: dict, layers: Iterable[dict] = ()) -> list[str]:
    """The columns a map view asks for: its hover fields, its popup title
    field and any its style uses."""
    fields = parse_field_list(view.get("hover_fields"))
    title = (view.get("popup_title_field") or "").strip()
    for name in [title] + style_fields(layers):
        if name and name not in fields and name not in INTERNAL_FIELDS:
            fields.append(name)
    return fields


def tile_url_template(
    resource_id: str,
    fields: list[str],
    version: Optional[str] = None,
    filters: Optional[str] = None,
) -> Optional[str]:
    """MapLibre tile URL for the map view, or None without a tile server.

    The ``{z}/{x}/{y}`` placeholders are left for MapLibre to fill in.

    :param filters: the view's filters as JSON (lib/filters.py).

    :param version: changes when the geometries do (e.g. the resource's
        ``spatialdata_last_geom_updated``), so tiles cached by Martin or
        browsers aren't reused after the data is georeferenced again. The
        tile function ignores it.
    """
    tileserver_url = (config.get("tileserver_url") or "").rstrip("/")
    if not tileserver_url:
        return None
    source = config.get("tile_function_source") or "public.spatialdata_tiles"
    query = {"resource": resource_id}
    if fields:
        query["fields"] = FIELD_LIST_SEPARATOR.join(fields)
    if filters:
        query["filters"] = filters
    if version:
        query["v"] = version
    return f"{tileserver_url}/{source}/{{z}}/{{x}}/{{y}}?{urlencode(query)}"
