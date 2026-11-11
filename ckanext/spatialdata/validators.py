# encoding: utf-8
from typing import Any

from ckan import authz
from ckan.common import _
from ckan.lib.navl.dictization_functions import Invalid, StopOnError, missing
from ckan.logic import validators


def json_object_list(value: Any) -> Any:
    """Make sure value can be serialized as a JSON object"""
    if value is None or value == "":
        return

    if type(value) != list:
        raise Invalid(_("The value should be a valid JSON list."))
    for item in value:
        if not validators.json_object(item):
            raise Invalid(_("All list items should be valid JSON objects."))

    return value


def geom_link(value: Any) -> Any:
    """Check a ``field->geom_field`` link and normalize its whitespace."""
    # imported here: lib.util imports the datastore backend
    from ckanext.spatialdata.lib.util import GEOM_LINK_SEPARATOR, parse_geom_link

    if value is None or value == "":
        return value
    try:
        local_field, geom_field = parse_geom_link(str(value))
    except ValueError as e:
        raise Invalid(_(str(e)))
    return f"{local_field}{GEOM_LINK_SEPARATOR}{geom_field}"


def field_list(value: Any) -> Any:
    """Normalize a comma-separated list of field names: ``"a, b,,a"`` → ``"a,b"``."""
    from ckanext.spatialdata.lib.tiles import FIELD_LIST_SEPARATOR, parse_field_list

    if value is None or value == "":
        return value
    return FIELD_LIST_SEPARATOR.join(parse_field_list(value))


def _stored_resource_value(key, data, context) -> Any:
    """The value already saved for this resource field, or None.

    Works on package schema keys, ``("resources", n, field)``.
    """
    if len(key) != 3 or key[0] != "resources":
        return None
    resource_id = data.get(("resources", key[1], "id"))
    if not resource_id or resource_id is missing:
        return None
    from ckan import model

    resource = model.Resource.get(resource_id)
    if resource is None:
        return None
    package = context.get("package")
    if package is not None and resource.package_id != package.id:
        return None
    return (resource.extras or {}).get(key[-1])


def sysadmin_only(key, data, errors, context) -> None:
    """Only sysadmins (or internal calls) can change this resource field.

    Otherwise, and whenever the field isn't sent at all, the saved value is
    kept. Unlike ``ignore_not_sysadmin``, which drops the field, so an
    editor's save (or a form that doesn't show the field) would erase it.
    """
    value = data.get(key)
    can_set = context.get("ignore_auth") or authz.is_sysadmin(context.get("user"))
    if can_set and value is not missing:
        return
    stored = _stored_resource_value(key, data, context)
    if stored is None:
        data.pop(key, None)
        raise StopOnError
    data[key] = stored
