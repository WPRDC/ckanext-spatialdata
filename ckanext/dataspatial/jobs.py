import logging
import traceback

from ckan.plugins import toolkit
from ckan.types import Context

from ckanext.spatialdata.lib import geofiles, postgis
from ckanext.spatialdata.lib.types import StatusCallback, GeoreferenceStatus

JOB_TYPE = "spatialdata_georeference"

logger = logging.getLogger(__name__)


def make_status_callback(
    resource_id: str,
    job_created: str,
    context: Context,
) -> StatusCallback:
    def callback(
        status: str,
        value: dict = None,
        error: str = None,
    ) -> None:
        data_dict = {
            "resource_id": resource_id,
            "job_created": job_created,
            "status": status,
            "error": None,
        }

        if error:
            logger.error(error)
            data_dict["error"] = error
        if value:
            data_dict["value"] = value

        return toolkit.get_action("spatialdata_hook")(context, data_dict)

    return callback


def georeference_datastore_table(
    resource_id: str,
    job_created: str,
    logger,
) -> None:
    status_callback = make_status_callback(
        resource_id, job_created, {"user": "default"}
    )

    resource = toolkit.get_action("resource_show")(
        {"user": "default"},
        {"id": resource_id},
    )

    # todo: wrap with try catch and
    try:
        if resource["format"].lower() == "geojson":
            geofiles.load_geojson_to_datastore(
                resource_id, status_callback=status_callback
            )

        elif "datastore_active" in resource and resource["datastore_active"]:
            postgis.prepare_and_populate_geoms(
                resource, status_callback=status_callback
            )

        else:
            status_callback(
                GeoreferenceStatus.ERROR,
                error="Can only georeference geojson files or resources pushed to datastore.",
            )
            raise toolkit.ValidationError(
                "Can only georeference geojson files or resources pushed to datastore."
            )
        status_callback(GeoreferenceStatus.COMPLETE, value={"notes": ""})

    except Exception as e:
        logger.error(traceback.format_exc())
        status_callback(GeoreferenceStatus.ERROR, error=traceback.format_exc())
