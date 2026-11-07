# encoding: utf-8
import logging
from typing import Any, cast

from ckan.common import CKANConfig
from ckan.plugins import SingletonPlugin, implements, interfaces, toolkit
from ckan.types import Context, Schema

from ckanext.spatialdata import auth, cli, views
from ckanext.spatialdata.actions import (
    spatialdata_submit,
    spatialdata_submit_package,
    spatialdata_hook,
    spatialdata_status,
    spatialdata_resource_list,
)
from ckanext.spatialdata.config import config
from ckanext.spatialdata.lib import map_style
from ckanext.spatialdata.helpers import (
    spatialdata_package_is_processed,
    spatialdata_processed_resources,
    spatialdata_status_description,
    spatialdata_tile_source,
)
from ckanext.spatialdata.schema import (
    spatialdata_modify_resource_schema,
    spatialdata_show_resource_schema,
)
from ckanext.spatialdata.search import datastore_query_extent
from ckanext.spatialdata.validators import json_object_list

log = logging.getLogger(__name__)

VIEW_TYPE = "spatialdata_view"


class SpatialdataPlugin(toolkit.DefaultDatasetForm, SingletonPlugin):
    """ """

    implements(interfaces.IValidators)
    implements(interfaces.IConfigurable)
    implements(interfaces.IActions)
    implements(interfaces.IAuthFunctions)
    implements(interfaces.IClick)
    implements(interfaces.IDatasetForm)
    implements(interfaces.IConfigurer)
    implements(interfaces.IBlueprint)
    implements(interfaces.ITemplateHelpers)
    implements(interfaces.IResourceView, inherit=True)

    # IValidators
    def get_validators(self):
        return {"json_object_list": json_object_list}

    # IConfigurer
    def update_config(self, config_: CKANConfig):
        toolkit.add_template_directory(config_, "templates")
        toolkit.add_resource("assets", "spatialdata")

    # IDatasetForm
    def _modify_package_schema(self, schema) -> Schema:
        cast(Schema, schema["resources"]).update(spatialdata_modify_resource_schema())
        return schema

    def show_package_schema(self) -> Schema:
        schema = super(SpatialdataPlugin, self).show_package_schema()
        # Add our custom_text field to the dataset schema.
        cast(Schema, schema["resources"]).update(spatialdata_show_resource_schema())
        return schema

    def create_package_schema(self) -> Schema:
        schema = super(SpatialdataPlugin, self).create_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def update_package_schema(self) -> Schema:
        schema = super(SpatialdataPlugin, self).update_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def is_fallback(self) -> bool:
        # Return True to register this plugin as the default handler for
        # package types not handled by any other IDatasetForm plugin.
        return True

    def package_types(self) -> list[str]:
        # This plugin doesn't handle any special package types, it just
        # registers itself as the default (above).
        return []

    # IConfigurable
    def configure(self, ckan_config):
        """

        :param ckan_config:

        """
        prefix = "spatialdata."
        config_items = config.keys()
        for long_name in ckan_config:
            if not long_name.startswith(prefix):
                continue
            name = long_name[len(prefix) :]

            if name in config_items:
                config[name] = ckan_config[long_name]
            else:
                raise toolkit.ValidationError(
                    {long_name: "Unknown configuration setting"}
                )

        if config["query_extent"] not in ["postgis", "solr"]:
            raise toolkit.ValidationError(
                {"spatialdata.query_extent": "Should be either of postgis or solr"}
            )

    # IActions
    def get_actions(self):
        """ """
        return {
            "spatialdata_submit": spatialdata_submit,
            "spatialdata_submit_package": spatialdata_submit_package,
            "spatialdata_hook": spatialdata_hook,
            "spatialdata_status": spatialdata_status,
            "spatialdata_resource_list": spatialdata_resource_list,
        }

    # IAuthFunctions
    def get_auth_functions(self):
        return {
            "spatialdata_submit": auth.spatialdata_submit,
            "spatialdata_submit_package": auth.spatialdata_submit_package,
            "spatialdata_hook": auth.spatialdata_hook,
        }

    # IClick
    def get_commands(self):
        return [cli.spatialdata, cli.spatialdata_init]

    # IBlueprint

    def get_blueprint(self):
        return views.get_blueprints()

    # ITemplateHelpers
    def get_helpers(self):
        return {
            "spatialdata_status_description": spatialdata_status_description,
            "spatialdata_package_is_processed": spatialdata_package_is_processed,
            "spatialdata_processed_resources": spatialdata_processed_resources,
            "spatialdata_default_map_style": lambda: map_style.dumps(
                map_style.DEFAULT_LAYERS
            ),
        }

    # IResourceView
    def info(self) -> dict[str, Any]:
        return {
            "name": VIEW_TYPE,
            "title": toolkit._("Map"),
            "default_title": toolkit._("Map"),
            "icon": "map",
            "requires_datastore": True,
            "iframed": True,
            "preview_enabled": True,
            "schema": {
                "style": [
                    toolkit.get_validator("ignore_empty"),
                    map_style.map_style_validator,
                ],
            },
        }

    def can_view(self, data_dict: dict[str, Any]) -> bool:
        # Tiles come from the tile server, so without one there's nothing to draw.
        return bool(config.get("tileserver_url")) and toolkit.asbool(
            data_dict["resource"].get("spatialdata_active")
        )

    def setup_template_variables(
        self, context: Context, data_dict: dict[str, Any]
    ) -> dict[str, Any]:
        from ckanext.spatialdata.lib.postgis import resource_extent

        resource_id = data_dict["resource"]["id"]
        tile_source = spatialdata_tile_source(resource_id)
        if not tile_source["tilejson_url"]:
            # A Map view made while a tile server was configured can outlive
            # the setting; the template shows a notice instead of a map.
            return {"tilejson_url": None}

        try:
            bounds = resource_extent(resource_id)
        except Exception:
            # The map still works without bounds; it just starts zoomed out.
            log.exception(f"Could not compute the extent of {resource_id}")
            bounds = None

        layers, style_error = map_style.layers_for_view(data_dict.get("resource_view"))

        return {
            "tilejson_url": tile_source["tilejson_url"],
            "source_layer": tile_source["source_id"],
            "basemap_style_url": config.get("basemap_style_url"),
            "tile_minzoom": config.get("tile_minzoom") or 0,
            "bounds": bounds,
            "layers": layers,
            "style_error": style_error,
        }

    def view_template(self, context: Context, data_dict: dict[str, Any]) -> str:
        return "spatialdata/spatialdata_view.html"

    def form_template(self, context: Context, data_dict: dict[str, Any]) -> str:
        return "spatialdata/spatialdata_view_form.html"
