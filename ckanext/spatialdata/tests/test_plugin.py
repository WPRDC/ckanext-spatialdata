"""The map resource view (IResourceView on SpatialdataPlugin)."""
import json

import pytest

from ckanext.spatialdata.lib import postgis
from ckanext.spatialdata.lib.map_style import DEFAULT_LAYERS
from ckanext.spatialdata.plugin import VIEW_TYPE, SpatialdataPlugin

RESOURCE_ID = "09900a13-ab5d-4e41-94f8-7e4d129e9a4c"
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
        "resource": resource or {"id": RESOURCE_ID, "spatialdata_active": True},
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

    def test_schema_has_style(self, plugin):
        assert "style" in plugin.info()["schema"]

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
    def tileserver(self, spatialdata_config):
        spatialdata_config(tileserver_url="https://tiles.example.org")

    def test_tiles_bounds_and_settings(self, plugin, spatialdata_config, extent):
        spatialdata_config(
            tileserver_url="https://tiles.example.org/",
            tile_source_id_format="table.{table}.{column}",
            basemap_style_url="https://basemap.example.org/style.json",
            tile_minzoom="9",
        )
        variables = plugin.setup_template_variables({}, view_data())

        assert variables["tilejson_url"] == (
            f"https://tiles.example.org/table.{RESOURCE_ID}._geom"
        )
        assert variables["source_layer"] == f"table.{RESOURCE_ID}._geom"
        assert variables["basemap_style_url"] == "https://basemap.example.org/style.json"
        assert variables["tile_minzoom"] == "9"
        assert variables["bounds"] == BOUNDS
        assert extent == [RESOURCE_ID]

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
        assert plugin.setup_template_variables({}, view_data()) == {"tilejson_url": None}
        assert extent == []
