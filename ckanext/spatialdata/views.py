# encoding: utf-8

import ckan.lib.base as base
import ckan.logic as logic
import ckan.plugins.toolkit as toolkit
from ckan.common import _
from flask import Blueprint
from flask.views import MethodView

from ckanext.spatialdata.lib.types import StatusResult

spatialdata = Blueprint("spatialdata", __name__)


def get_blueprints():
    return [spatialdata]


def render_resource_data_view(package_id: str, resource_id: str):
    try:
        toolkit.check_access("spatialdata_submit", {}, {"resource_id": resource_id})
    except logic.NotAuthorized:
        base.abort(403, _("Only sysadmins can georeference resources."))

    try:
        pkg_dict = toolkit.get_action("package_show")({}, {"id": package_id})
        resource = toolkit.get_action("resource_show")({}, {"id": resource_id})

        # backward compatibility with old templates
        toolkit.g.pkg_dict = pkg_dict
        toolkit.g.resource = resource

    except (logic.NotFound, logic.NotAuthorized):
        base.abort(404, _("Resource not found"))

    # get job status
    status: StatusResult = toolkit.get_action("spatialdata_status")(
        {},
        {"resource_id": resource_id},
    )

    return base.render(
        "spatialdata/resource_spatialdata.html",
        extra_vars={
            # resource_edit_base.html and its parents expect these names
            "pkg": pkg_dict,
            "pkg_dict": pkg_dict,
            "resource": resource,
            "res": resource,
            "status": status,
        },
    )


class ResourceDataView(MethodView):
    def post(self, id: str, resource_id: str):
        """Submit job and return its status"""
        try:
            toolkit.get_action("spatialdata_submit")(
                {"user": toolkit.current_user.name}, {"resource_id": resource_id}
            )
        except logic.NotAuthorized:
            base.abort(403, _("Only sysadmins can georeference resources."))
        except logic.ValidationError as e:
            toolkit.h.flash_error(str(e.error_dict or e))

        return toolkit.redirect_to(
            "spatialdata.resource_spatialdata", id=id, resource_id=resource_id
        )

    def get(self, id: str, resource_id: str):
        """Return status of the georeference job for this resource if it exists"""
        return render_resource_data_view(id, resource_id)


spatialdata.add_url_rule(
    "/dataset/<id>/resource_spatialdata/<resource_id>",
    view_func=ResourceDataView.as_view(str("resource_spatialdata")),
)
