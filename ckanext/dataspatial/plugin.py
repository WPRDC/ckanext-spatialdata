# encoding: utf-8
from typing import cast

from ckan.common import CKANConfig
from ckan.plugins import SingletonPlugin, implements, interfaces, toolkit
from ckan.types import Schema

from ckanext.spatialdata import cli, views
from ckanext.spatialdata.actions import (
    spatialdata_submit,
    spatialdata_hook,
    spatialdata_status,
    spatialdata_resource_list,
)
from ckanext.spatialdata.config import config
from ckanext.spatialdata.helpers import spatialdata_status_description
from ckanext.spatialdata.schema import (
    spatialdata_modify_resource_schema,
    spatialdata_show_resource_schema,
)
from ckanext.spatialdata.search import datastore_query_extent
from ckanext.spatialdata.validators import json_object_list


class spatialdataPlugin(toolkit.DefaultDatasetForm, SingletonPlugin):
    """ """

    implements(interfaces.IValidators)
    implements(interfaces.IConfigurable)
    implements(interfaces.IActions)
    implements(interfaces.IClick)
    implements(interfaces.IDatasetForm)
    implements(interfaces.IConfigurer)
    implements(interfaces.IBlueprint)
    implements(interfaces.ITemplateHelpers)

    # IValidators
    def get_validators(self):
        return {"json_object_list": json_object_list}

    # IConfigurer
    def update_config(self, config_: CKANConfig):
        toolkit.add_template_directory(config_, "templates")

    # IDatasetForm
    def _modify_package_schema(self, schema) -> Schema:
        cast(Schema, schema["resources"]).update(spatialdata_modify_resource_schema())
        return schema

    def show_package_schema(self) -> Schema:
        schema = super(spatialdataPlugin, self).show_package_schema()
        # Add our custom_text field to the dataset schema.
        cast(Schema, schema["resources"]).update(spatialdata_show_resource_schema())
        return schema

    def create_package_schema(self) -> Schema:
        schema = super(spatialdataPlugin, self).create_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def update_package_schema(self) -> Schema:
        schema = super(spatialdataPlugin, self).update_package_schema()
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
            "spatialdata_hook": spatialdata_hook,
            "spatialdata_status": spatialdata_status,
            "spatialdata_resource_list": spatialdata_resource_list,
        }

    # IClick
    def get_commands(self):
        return [cli.spatialdata, cli.spatialdata_init]

    # IBlueprint

    def get_blueprint(self):
        return views.get_blueprints()

    # ITemplateHelpers
    def get_helpers(self):
        return {"spatialdata_status_description": spatialdata_status_description}
