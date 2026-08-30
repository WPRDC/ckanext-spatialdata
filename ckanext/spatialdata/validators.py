# encoding: utf-8
from typing import Any

from ckan.common import _
from ckan.lib.navl.dictization_functions import Invalid
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
