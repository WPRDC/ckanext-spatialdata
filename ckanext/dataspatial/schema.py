import ckan.plugins.toolkit as tk
from ckan.types import Schema

from ckanext.spatialdata.validators import json_object_list

boolean_validator = tk.get_validator("boolean_validator")
isodate = tk.get_validator("isodate")
ignore_empty = tk.get_validator("ignore_empty")
ignore_not_sysadmin = tk.get_validator("ignore_not_sysadmin")
resource_id_exists = tk.get_validator("resource_id_exists")
default = tk.get_validator("default")

convert_to_json_if_string = tk.get_converter("convert_to_json_if_string")


def spatialdata_modify_resource_schema() -> Schema:
    return {
        # status
        "spatialdata_active": [boolean_validator],
        "spatialdata_status": [ignore_empty],
        "spatialdata_last_geom_updated": [ignore_empty, isodate],
        # for preparing tabular files
        "spatialdata_longitude_field": [ignore_not_sysadmin, ignore_empty],
        "spatialdata_latitude_field": [ignore_not_sysadmin, ignore_empty],
        "spatialdata_wkt_field": [ignore_not_sysadmin, ignore_empty],
        # for preparing geojson
        "spatialdata_fields_definition": [
            ignore_not_sysadmin,
            ignore_empty,
            convert_to_json_if_string,
            json_object_list,
        ],
        # for linking non-geographic tables
        "spatialdata_geom_resource": [
            ignore_not_sysadmin,
            ignore_empty,
            resource_id_exists,
        ],
        "spatialdata_geom_link": [ignore_not_sysadmin, ignore_empty],
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
