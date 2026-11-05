# encoding: utf-8
"""Authorization functions for spatialdata actions.

Triggering georeferencing is limited to sysadmins who can also update the
dataset (``package_update``). Sysadmins always pass ``package_update`` today,
but the explicit check keeps the rule correct if that ever changes.
"""
from typing import Optional

from ckan import authz, model
from ckan.plugins import toolkit
from ckan.types import AuthResult, Context, DataDict

_ = toolkit._


def _sysadmin_with_package_update(
    context: Context, package_id: Optional[str]
) -> AuthResult:
    user = context.get("user")
    if not authz.is_sysadmin(user):
        return {
            "success": False,
            "msg": _("Only sysadmins can georeference data."),
        }
    if package_id:
        try:
            toolkit.check_access("package_update", context, {"id": package_id})
        except toolkit.NotAuthorized:
            return {
                "success": False,
                "msg": _("User %s not authorized to edit this dataset.") % user,
            }
    return {"success": True}


@toolkit.auth_sysadmins_check
def spatialdata_submit(context: Context, data_dict: DataDict) -> AuthResult:
    resource = model.Resource.get(data_dict.get("resource_id") or "")
    return _sysadmin_with_package_update(
        context, resource.package_id if resource else None
    )


@toolkit.auth_sysadmins_check
def spatialdata_submit_package(context: Context, data_dict: DataDict) -> AuthResult:
    package = model.Package.get(data_dict.get("id") or "")
    return _sysadmin_with_package_update(context, package.id if package else None)


def spatialdata_hook(context: Context, data_dict: DataDict) -> AuthResult:
    # Only called by background jobs, which run as the site user (a sysadmin).
    return {
        "success": False,
        "msg": _("Only sysadmins can update georeferencing job status."),
    }
