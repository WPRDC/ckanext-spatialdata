"""The map resource view (IResourceView on SpatialdataPlugin)."""
import json

import pytest

from ckanext.spatialdata.lib import postgis
from ckanext.spatialdata.lib.map_style import DEFAULT_LAYERS
from ckanext.spatialdata.plugin import VIEW_TYPE, SpatialdataPlugin

RESOURCE_ID = "09900a13-ab5d-4e41-94f8-7e4d129e9a4c"
PACKAGE_ID = "5b6f6a2c-1d0e-4f6c-9d7e-3a2b1c0d9e8f"
BOUNDS = [-80.36, 40.19, -79.69, 40.67]

pytestmark = pytest.mark.usefixtures("with_request_context")


@pytest.fixture
def plugin():
    return SpatialdataPlugin()


@pytest.fixture
def extent(monkeypatch):
    """Stub the PostGIS extent query; returns the list of resource ids asked for."""
    calls = []

    def fake(resource_id):
        calls.append(resource_id)
        return BOUNDS

    monkeypatch.setattr(postgis, "resource_extent", fake)
    return calls


def view_data(resource=None, resource_view=None):
    return {
        "resource": resource
        or {"id": RESOURCE_ID, "package_id": PACKAGE_ID, "spatialdata_active": True},
        "resource_view": resource_view or {},
    }


class TestInfo:
    def test_name_and_title(self, plugin):
        info = plugin.info()
        assert info["name"] == VIEW_TYPE == "spatialdata_view"
        assert info["title"] == "Map"

    def test_iframed_with_preview(self, plugin):
        info = plugin.info()
        assert info["iframed"] is True
        assert info["preview_enabled"] is True
        assert info["requires_datastore"] is True

    def test_schema_has_style_and_popups(self, plugin):
        schema = plugin.info()["schema"]
        for key in ("style", "popup_title_field", "hover_fields", "popup_template"):
            assert key in schema

    def test_templates(self, plugin):
        assert plugin.view_template({}, {}) == "spatialdata/spatialdata_view.html"
        assert plugin.form_template({}, {}) == "spatialdata/spatialdata_view_form.html"


class TestCanView:
    @pytest.mark.parametrize(
        "tileserver_url, active, expected",
        [
            ("https://tiles.example.org", True, True),
            ("https://tiles.example.org", "true", True),
            ("https://tiles.example.org", False, False),
            ("https://tiles.example.org", None, False),
            ("", True, False),
        ],
    )
    def test_needs_tileserver_and_georeferencing(
        self, plugin, spatialdata_config, tileserver_url, active, expected
    ):
        spatialdata_config(tileserver_url=tileserver_url)
        resource = {"id": RESOURCE_ID, "spatialdata_active": active}
        assert plugin.can_view({"resource": resource, "package": {}}) is expected


class TestSetupTemplateVariables:
    @pytest.fixture(autouse=True)
    def tileserver(self, spatialdata_config, monkeypatch):
        spatialdata_config(tileserver_url="https://tiles.example.org")
        # the plugin's blueprint isn't registered in these unit tests
        monkeypatch.setattr(
            "ckan.plugins.toolkit.url_for",
            lambda endpoint, id, resource_id, row_id, **query: (
                f"/{id}/{resource_id}/feature/{row_id}"
                + "".join(f"?{k}={v}" for k, v in query.items())
            ),
        )

    def test_tiles_bounds_and_settings(self, plugin, spatialdata_config, extent):
        spatialdata_config(
            tileserver_url="https://tiles.example.org/",
            basemap_style_url="https://basemap.example.org/style.json",
            tile_minzoom="9",
        )
        variables = plugin.setup_template_variables({}, view_data())

        assert variables["tile_url"] == (
            "https://tiles.example.org/public.spatialdata_tiles/{z}/{x}/{y}"
            f"?resource={RESOURCE_ID}"
        )
        assert variables["source_layer"] == "features"
        assert variables["feature_url"] == f"/{PACKAGE_ID}/{RESOURCE_ID}/feature/0"
        assert variables["title_field"] == ""
        assert variables["hover_fields"] == []
        assert variables["basemap_style_url"] == "https://basemap.example.org/style.json"
        assert variables["tile_minzoom"] == "9"
        assert variables["bounds"] == BOUNDS
        assert extent == [RESOURCE_ID]

    def test_popup_fields_and_version(self, plugin, extent):
        resource = {
            "id": RESOURCE_ID,
            "package_id": PACKAGE_ID,
            "spatialdata_active": True,
            "spatialdata_last_geom_updated": "2026-11-10T23:18:12",
        }
        layers = [{"type": "circle", "paint": {"circle-color": ["get", "COLOR"]}}]
        view = {
            "id": "view-1",
            "style": json.dumps(layers),
            "hover_fields": "STATUS,CREATED_ON",
            "popup_title_field": "REQUEST_TYPE",
        }
        variables = plugin.setup_template_variables({}, view_data(resource, view))
        assert variables["tile_url"].endswith(
            "?resource=" + RESOURCE_ID
            + "&fields=STATUS%2CCREATED_ON%2CREQUEST_TYPE%2CCOLOR"
            + "&v=2026-11-10T23%3A18%3A12"
        )
        assert variables["title_field"] == "REQUEST_TYPE"
        assert variables["hover_fields"] == ["STATUS", "CREATED_ON"]
        # clicks render with this view's saved template
        assert variables["feature_url"] == (
            f"/{PACKAGE_ID}/{RESOURCE_ID}/feature/0?view=view-1"
        )

    def test_unsaved_view_has_no_view_id(self, plugin, extent):
        variables = plugin.setup_template_variables({}, view_data())
        assert "?" not in variables["feature_url"]

    def test_default_layers(self, plugin, extent):
        variables = plugin.setup_template_variables({}, view_data())
        assert variables["layers"] == DEFAULT_LAYERS
        assert variables["style_error"] is None

    def test_custom_layers(self, plugin, extent):
        layers = [{"type": "circle", "paint": {"circle-color": "#e4572e"}}]
        variables = plugin.setup_template_variables(
            {}, view_data(resource_view={"style": json.dumps(layers)})
        )
        assert variables["layers"] == layers

    def test_invalid_style_reports_error(self, plugin, extent):
        variables = plugin.setup_template_variables(
            {}, view_data(resource_view={"style": '[{"type": "raster"}]'})
        )
        assert variables["layers"] == DEFAULT_LAYERS
        assert "must be one of" in variables["style_error"]

    def test_extent_failure_leaves_bounds_empty(self, plugin, monkeypatch):
        def broken(resource_id):
            raise RuntimeError("database is down")

        monkeypatch.setattr(postgis, "resource_extent", broken)
        variables = plugin.setup_template_variables({}, view_data())
        assert variables["bounds"] is None

    def test_without_tileserver_skips_map_and_extent(
        self, plugin, spatialdata_config, extent
    ):
        # a Map view made while a tile server was configured can outlive it
        spatialdata_config(tileserver_url="")
        assert plugin.setup_template_variables({}, view_data()) == {"tile_url": None}
        assert extent == []
