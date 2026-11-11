import ckan.plugins.toolkit as tk
from ckan.types import Schema

from ckanext.spatialdata.validators import (
    geom_link,
    json_object_list,
    sysadmin_only,
)

boolean_validator = tk.get_validator("boolean_validator")
isodate = tk.get_validator("isodate")
ignore_empty = tk.get_validator("ignore_empty")
unicode_safe = tk.get_validator("unicode_safe")
resource_id_exists = tk.get_validator("resource_id_exists")
default = tk.get_validator("default")

convert_to_json_if_string = tk.get_converter("convert_to_json_if_string")


def spatialdata_modify_resource_schema() -> Schema:
    # Keep in step with the resource fields in ckanext-wprdctheme's
    # dataset_schema.yaml, which replaces this schema where scheming is used.
    return {
        # status, set by georeferencing jobs
        "spatialdata_active": [sysadmin_only, boolean_validator],
        "spatialdata_status": [sysadmin_only, ignore_empty, unicode_safe],
        "spatialdata_last_geom_updated": [sysadmin_only, ignore_empty, unicode_safe],
        # for preparing tabular files
        "spatialdata_longitude_field": [sysadmin_only, ignore_empty, unicode_safe],
        "spatialdata_latitude_field": [sysadmin_only, ignore_empty, unicode_safe],
        "spatialdata_wkt_field": [sysadmin_only, ignore_empty, unicode_safe],
        # for preparing geojson
        "spatialdata_fields_definition": [
            sysadmin_only,
            ignore_empty,
            convert_to_json_if_string,
            json_object_list,
        ],
        # for linking non-geographic tables
        "spatialdata_geom_resource": [sysadmin_only, ignore_empty, resource_id_exists],
        "spatialdata_geom_link": [sysadmin_only, ignore_empty, geom_link],
    }


def spatialdata_show_resource_schema() -> Schema:
    return {
        "spatialdata_status": [default("inactive")],
        "spatialdata_longitude_field": [ignore_empty, default(None)],
        "spatialdata_latitude_field": [ignore_empty, default(None)],
        "spatialdata_wkt_field": [ignore_empty, default(None)],
        "spatialdata_fields_definition": [ignore_empty, default(None)],
        "spatialdata_geom_resource": [ignore_empty, default(None)],
        "spatialdata_geom_link": [ignore_empty, default(None)],
        "spatialdata_last_geom_updated": [ignore_empty, default(None)],
        "spatialdata_active": [boolean_validator, ignore_empty, default(False)],
    }
