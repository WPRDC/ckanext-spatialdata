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
