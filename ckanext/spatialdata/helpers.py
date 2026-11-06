from ckan.plugins import toolkit
from ckanext.spatialdata.lib.types import GeoreferenceStatus


def spatialdata_status_description(status: dict) -> str:
    _ = toolkit._

    if status["status"]:
        captions = {
            GeoreferenceStatus.COMPLETE.value: _("Complete"),
            GeoreferenceStatus.PENDING.value: _("Pending"),
            GeoreferenceStatus.WORKING.value: _("Working"),
            GeoreferenceStatus.SUBMITTING.value: _("Submitting"),
            GeoreferenceStatus.ERROR.value: _("Error"),
            GeoreferenceStatus.NOT_STARTED.value: _("Not georeferenced"),
        }
        return captions.get(status["status"], _(status["status"]))
    else:
        return _("Not Uploaded Yet")


def spatialdata_package_is_processed(pkg: dict) -> bool:
    """True if any resource in the dataset has been georeferenced by spatialdata."""
    return any(
        toolkit.asbool(res.get("spatialdata_active"))
        for res in pkg.get("resources") or []
    )


def spatialdata_tile_source(resource_id: str) -> dict:
    """Martin vector tile source for a resource's geometry column.

    Returns ``source_id`` (also the layer name inside the tiles) and
    ``tilejson_url`` (None if no tile server is configured).
    """
    from ckanext.spatialdata.config import config
    from ckanext.spatialdata.lib.postgis import GEOM_FIELD

    tileserver_url = (config.get("tileserver_url") or "").rstrip("/")
    source_id_format = config.get("tile_source_id_format") or "table.{table}.{column}"
    source_id = source_id_format.format(
        table=resource_id, column=GEOM_FIELD, schema="public"
    )
    return {
        "source_id": source_id,
        "tilejson_url": f"{tileserver_url}/{source_id}" if tileserver_url else None,
    }


# Downtown Pittsburgh; only used to make the example query concrete.
_EXAMPLE_ENVELOPE = (-80.0200, 40.4350, -79.9900, 40.4500)


def spatialdata_processed_resources(pkg: dict) -> list[dict]:
    """Details for each georeferenced resource in a dataset, for the badge modal.

    Each item has the resource ``id`` and ``name``, an example PostGIS ``sql``
    query, the ``sql_api_url`` that runs it through ``datastore_search_sql``,
    and the ``tilejson_url`` for the resource's vector tiles (None if no tile
    server is configured).
    """
    # imported here to avoid loading the db layer when templates load helpers
    from ckanext.spatialdata.lib.postgis import GEOM_FIELD

    xmin, ymin, xmax, ymax = _EXAMPLE_ENVELOPE

    resources = []
    for res in pkg.get("resources") or []:
        if not toolkit.asbool(res.get("spatialdata_active")):
            continue
        sql = (
            f'SELECT * FROM "{res["id"]}"\n'
            f'WHERE ST_Intersects(\n'
            f'  "{GEOM_FIELD}",\n'
            f"  ST_MakeEnvelope({xmin}, {ymin}, {xmax}, {ymax}, 4326)\n"
            f")\n"
            f"LIMIT 100"
        )
        tilejson_url = spatialdata_tile_source(res["id"])["tilejson_url"]
        resources.append(
            {
                "id": res["id"],
                "name": toolkit.h.resource_display_name(res),
                "sql": sql,
                "sql_api_url": toolkit.url_for(
                    "api.action",
                    ver=3,
                    logic_function="datastore_search_sql",
                    sql=" ".join(sql.split()),
                    _external=True,
                ),
                "tilejson_url": tilejson_url,
            }
        )
    return resources
