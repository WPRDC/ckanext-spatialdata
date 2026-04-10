# encoding: utf-8
import datetime
import json
import logging

import ckan.lib.jobs as rq_jobs
from ckan.logic import NotFound, side_effect_free
from ckan.plugins import toolkit
from ckan.types import Context, DataDict
from dateutil.parser import isoparse as parse_iso_date
from dateutil.parser import parse as parse_date

from ckanext.spatialdata import jobs
from ckanext.spatialdata.jobs import JOB_TYPE
from ckanext.spatialdata.lib.postgis import prepare_and_populate_geoms
from ckanext.spatialdata.lib.types import GeoreferenceStatus, StatusResult

enqueue_job = toolkit.enqueue_job
get_queue = rq_jobs.get_queue

config = toolkit.config

logger = logging.getLogger(__name__)


TASK_TYPE = "spatialdata"
TASK_KEY = "spatialdata"


def spatialdata_submit(context: Context, data_dict: DataDict) -> bool:
    """Submit a job to be georeferenced.

    Returns `True` if the job has been submitted and `False` if the job
    has not been submitted, i.e. if a bug is encountered
    """
    # validate arguments and setup first
    resource_id = toolkit.get_or_bust(data_dict, "resource_id")
    try:
        resource_dict = toolkit.get_action("resource_show")(
            context,
            {
                "id": resource_id,
            },
        )
        if (
            not resource_dict.get("datastore_active")
            and resource_dict.get("format").lower() != "geojson"
        ):
            raise toolkit.ValidationError(
                "Resource data must be loaded into the datastore."
            )
    except toolkit.ObjectNotFound:
        raise toolkit.ValidationError(f"Resource with ID {resource_id} does not exist.")

    # check if is a job is already running properly for this resource
    extant_task_id = None
    try:
        extant_task = toolkit.get_action("task_status_show")(
            context,
            {
                "entity_id": resource_id,
                "task_type": TASK_TYPE,
                "key": TASK_KEY,
            },
        )

        # check if extant job is working properly
        # todo: add config options
        assume_task_stale_after = datetime.timedelta(seconds=3600)
        assume_task_stillborn_after = datetime.timedelta(seconds=5)
        if extant_task.get("state") == GeoreferenceStatus.PENDING:
            import re  # here because it takes a moment to load

            queued_res_ids = [
                re.search(r"'resource_id': u?'([^']+)'", job.description).groups()[0]
                for job in get_queue().get_jobs()
                if JOB_TYPE in str(job)
            ]
            updated = parse_iso_date(extant_task["last_updated"])
            time_since_last_updated = datetime.datetime.utcnow() - updated

            if (
                resource_id not in queued_res_ids
                and time_since_last_updated > assume_task_stillborn_after
            ):
                logger.info(
                    f"A pending task was found ({extant_task['id']}), "
                    f"but its not found in the queue ({queued_res_ids}) "
                    f"and is {time_since_last_updated} hours old",
                )
            elif time_since_last_updated > assume_task_stale_after:
                logger.info(
                    f"A pending task was found {extant_task['id']}, "
                    f"but it is {time_since_last_updated} hours old",
                )
            else:
                logger.info(
                    f"A healthy pending task was found {extant_task['id']} for this resource, "
                    f"so skipping this duplicate task"
                )
                return False

        extant_task_id = extant_task["id"]
    except toolkit.ObjectNotFound:
        pass

    # set task status to `submitting`
    task = {
        "entity_id": resource_id,
        "entity_type": "resource",
        "task_type": TASK_TYPE,
        "last_updated": str(datetime.datetime.utcnow()),
        "state": "submitting",
        "key": TASK_KEY,
        "value": "{}",
        "error": None,
    }
    if extant_task_id:
        task["id"] = extant_task_id
    model = context["model"]
    toolkit.get_action("task_status_update")(
        {"session": model.meta.create_local_session(), "ignore_auth": True}, task
    )

    # todo add to config
    timeout = config.get("ckanext.spatialdata.job_timeout", "3600")
    try:
        job = enqueue_job(
            jobs.georeference_datastore_table,
            [resource_id, task["last_updated"], logger],
            rq_kwargs={"timeout": timeout},
        )
    except Exception as e:
        logger.exception(e)
        return False

    logger.debug(f"Enqueued spatialdata job {job.id} for resource {resource_id}")

    # update task status
    task["value"] = json.dumps({"job_id": job.id})
    task["state"] = GeoreferenceStatus.SUBMITTING.value
    task["last_updated"] = str(datetime.datetime.utcnow())
    task["error"] = None
    toolkit.get_action("task_status_update")(
        {"session": model.meta.create_local_session(), "ignore_auth": True}, task
    )
    return True


def spatialdata_hook(context: Context, data_dict: DataDict):
    """Called occasionally from georeferencing jobs,
    providing status information to be used to update ckan task statuses.

    :param context: Current context
    :param data_dict: Parameters:
      - resource_id: The ID of the resource the job is working on.
      - status: The current status of the job.
      - job_created: ISO str of datetime when job was created.
      - value: Dict with data to store in value field
    """
    # todo: figure out what we need passed in data_dict
    #   - status, task_created, error (optional),
    resource_id, status, job_created = toolkit.get_or_bust(
        data_dict,
        ["resource_id", "status", "job_created"],
    )

    task = toolkit.get_action("task_status_show")(
        context, {"entity_id": resource_id, "task_type": TASK_TYPE, "key": TASK_KEY}
    )

    resubmit = False

    if status == GeoreferenceStatus.COMPLETE:
        resource_dict = toolkit.get_action("resource_show")(
            context, {"id": resource_id}
        )

        # todo: Create default views for resource if necessary (if using tileserver)

        # Check if the uploaded file has been modified in the meantime
        if resource_dict.get("last_modified") and job_created:
            try:
                last_modified_datetime = parse_date(resource_dict["last_modified"])
                job_created_datetime = parse_date(job_created)
                if last_modified_datetime > job_created_datetime:
                    logger.debug(
                        f"File changed since job started {last_modified_datetime} > {job_created_datetime}"
                    )
                    resubmit = True
            except ValueError:
                pass

    error = data_dict.get("error")
    if error:
        logger.error(error)
    value = data_dict.get("value", {})

    # update task status
    task["state"] = status.value
    task["last_updated"] = str(datetime.datetime.utcnow())
    task["error"] = error
    task["value"] = json.dumps(value)
    context["ignore_auth"] = True
    toolkit.get_action("task_status_update")(context, task)

    if resubmit:
        toolkit.check_access(
            "spatialdata_submit", context, {"resource_id": resource_id}
        )
        logger.debug(
            f"Resource {resource_id} has been modified. Resubmitting for georeferencing."
        )
        toolkit.get_action("spatialdata_submit")(context, {"resource_id": resource_id})


def spatialdata_status(context: Context, data_dict: DataDict) -> StatusResult:
    resource_id = toolkit.get_or_bust(data_dict, "resource_id")
    try:
        task = toolkit.get_action("task_status_show")(
            context,
            {
                "entity_id": resource_id,
                "task_type": TASK_TYPE,
                "key": TASK_KEY,
            },
        )

        status = task.get("state", "UNKNOWN")
        last_updated = task.get("last_updated")
        # parse json value
        value: dict = json.loads(task.get("value", {}))
        job_id: str = value.get("job_id")
        rows_completed = value.get("rows_completed")
        notes = value.get("notes")
        error = task.get("error")

        return {
            "job_id": job_id,
            "status": status,
            "rows_completed": rows_completed,
            "notes": notes,
            "error": error,
            "last_updated": last_updated,
        }
    except NotFound:
        return {
            "status": GeoreferenceStatus.NOT_STARTED.value,
        }


def spatialdata_populate(context: Context, data_dict: DataDict):
    """Add geom column to the given resource, and optionally populate them.

    Either latitude_field and longitude_field or wkt_field parameters are required unless they are
        already stored in the resource's metadata.

    Providing these will update the resource's metadata.

    :param context: Current context
    :param data_dict: Parameters:
      - resource_id: The resource for which to create geom columns; REQUIRED
      - latitude_field: The existing latitude field in the column.
      - longitude_field: The existing longitude field in the column,
      - wkt_field: The existing wkt field in the column
    """
    try:
        resource_id = data_dict["resource_id"]
    except KeyError:
        raise toolkit.ValidationError({"resource_id": "A Resource id is required"})

    # update metadata if field arguments are passed
    resource = toolkit.get_action("resource_show")(context, {"id": resource_id})

    lat_field = resource.get("spatialdata_latitude_field")
    lng_field = resource.get("spatialdata_longitude_field")
    wkt_field = resource.get("spatialdata_wkt_field")

    arg_lat_field = data_dict.get("latitude_field")
    arg_lng_field = data_dict.get("longitude_field")
    arg_wkt_field = data_dict.get("wkt_field")

    patch_dict = {}
    if arg_lat_field and arg_lat_field != lat_field:
        patch_dict["spatialdata_latitude_field"] = arg_lat_field
    if arg_lng_field and arg_lng_field != lng_field:
        patch_dict["spatialdata_longitude_field"] = arg_lng_field
    if arg_wkt_field and arg_wkt_field != wkt_field:
        patch_dict["spatialdata_wkt_field"] = arg_wkt_field

    # if fields are provided, update metadata with them
    resource = toolkit.get_action("resource_patch")(context, patch_dict)

    # ensure the resource has the minimum metadata
    lat_field = resource.get("spatialdata_latitude_field")
    lng_field = resource.get("spatialdata_longitude_field")
    wkt_field = resource.get("spatialdata_wkt_field")
    if not (lat_field and lng_field) and not wkt_field:
        raise toolkit.ValidationError(
            "Missing required source column(s). Provide lat/lng fieldnames or a wkt field name."
        )

    # prepare and populate the columns
    prepare_and_populate_geoms(resource)


@side_effect_free
def spatialdata_resource_list(context: Context, data_dict: DataDict):
    active_resources = toolkit.get_action("resource_search")(
        context, {"query": "spatialdata_status:active"}
    )["results"]
    fields = [
        "id",
        "package_id",
        "url",
        "format",
        "spatialdata_active",
        "spatialdata_fields_definition",
        "spatialdata_last_geom_updated",
        "spatialdata_status",
    ]
    result = []
    for resource in active_resources:
        result.append({field: resource.get(field) for field in fields})
    return result
