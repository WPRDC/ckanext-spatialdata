# encoding: utf-8
import logging

import click

from ckanext.spatialdata.lib.geofiles import load_geojson_to_datastore
from ckanext.spatialdata.lib.postgis import (
    create_postgis_columns,
    create_postgis_index,
    populate_postgis_columns,
)
from ckanext.spatialdata.lib.util import update_fulltext_trigger
from ckanext.spatialdata.lib.types import GEOMETRY_TYPES

log = logging.getLogger("ckan")


@click.command()
@click.argument("action")
@click.argument("resource_id")
@click.option("--latitude-field")
@click.option("--longitude-field")
@click.option("--wkt-field")
@click.option("--geom-type")
def spatialdata(
    action: str,
    resource_id: str,
    latitude_field: str,
    longitude_field: str,
    wkt_field: str,
    geom_type: str,
):
    """Run spatialdata COMMAND to create or populate postgis spatial columns on datasets.

    ACTION: one of (create-columns | create-index | populate-columns)
    RESOURCE_ID: ID of resource to modify/update
    """
    # Validate arguments
    if action not in [
        "create-columns",
        "create-index",
        "populate-columns",
        "load-file",
    ]:
        raise click.BadArgumentUsage(
            "Please specify one of create-columns, create-index or populate-columns"
        )

    if action == "load-file":
        load_geojson_to_datastore(resource_id)

    if action == "populate-columns" and (
        not (latitude_field and longitude_field) and not wkt_field
    ):
        raise click.UsageError(
            "Latitude and Longitude fields or a WKT field need to be specified to populate columns."
        )

    if action == "create-columns" and (
        not geom_type or not geom_type.upper() in GEOMETRY_TYPES
    ):
        raise click.UsageError(f"geom-type must be one of {', '.join(GEOMETRY_TYPES)}.")

    # Actions
    if action == "create-columns":
        click.echo(f"Creating postgis columns on {resource_id}.")
        create_postgis_columns(resource_id, geom_type)

    if action == "create-index":
        click.echo(f"Creating index on geometry columns in {resource_id}.")
        create_postgis_index(resource_id)

    if action == "populate-columns":
        click.echo(f"Populating postgis columns on {resource_id}...")
        populate_postgis_columns(
            resource_id,
            lat_field=latitude_field,
            lng_field=longitude_field,
            wkt_field=wkt_field,
        )
    click.echo("Done!")


@click.command()
def spatialdata_init():
    click.echo("Updating _full_text update trigger.")
    update_fulltext_trigger()
    click.echo("Done!")
