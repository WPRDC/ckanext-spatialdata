"""What the templates show with and without a tile server configured."""
import pytest
from ckan.lib import datapreview
from ckan.plugins import toolkit

from ckanext.spatialdata.plugin import VIEW_TYPE, SpatialdataPlugin

RESOURCE_ID = "09900a13-ab5d-4e41-94f8-7e4d129e9a4c"
TILESERVER = "https://tiles.example.org"

pytestmark = [
    pytest.mark.ckan_config("ckan.plugins", "spatialdata"),
    pytest.mark.usefixtures("with_plugins"),
]


@pytest.fixture
def resource():
    return {
        "id": RESOURCE_ID,
        "name": "Boundary",
        "format": "GeoJSON",
        "datastore_active": True,
        "spatialdata_active": True,
        "package_id": "pkg-1",
    }


@pytest.fixture
def package(resource):
    return {"id": "pkg-1", "name": "boundary", "type": "dataset", "resources": [resource]}


def render_modal(package):
    return toolkit.render_snippet("spatialdata/snippets/processed_modal.html", {"pkg": package})


@pytest.mark.usefixtures("with_request_context")
class TestMappableModal:
    def test_no_tile_links_without_tileserver(self, spatialdata_config, package):
        spatialdata_config(tileserver_url="")
        html = render_modal(package)
        # the PostGIS / SQL docs still apply without a tile server
        assert 'id="spatialdata-modal"' in html
        assert "ST_Intersects" in html
        assert "TileJSON" not in html
        assert "Vector tiles" not in html

    def test_tile_links_with_tileserver(self, spatialdata_config, package):
        spatialdata_config(tileserver_url=TILESERVER)
        html = render_modal(package)
        assert "Vector tiles" in html
        assert f"{TILESERVER}/table.{RESOURCE_ID}._geom" in html

    def test_nothing_for_unprocessed_dataset(self, spatialdata_config, package):
        spatialdata_config(tileserver_url=TILESERVER)
        package["resources"][0]["spatialdata_active"] = False
        assert 'id="spatialdata-modal"' not in render_modal(package)


@pytest.mark.usefixtures("with_request_context")
class TestMapViewOffered:
    """The view types CKAN offers when adding a view to a resource."""

    def allowed(self, resource, package):
        return [
            plugin.info()["name"]
            for plugin in datapreview.get_allowed_view_plugins(
                {"resource": resource, "package": package}
            )
        ]

    def test_not_offered_without_tileserver(self, spatialdata_config, resource, package):
        spatialdata_config(tileserver_url="")
        assert VIEW_TYPE not in self.allowed(resource, package)

    def test_offered_with_tileserver(self, spatialdata_config, resource, package):
        spatialdata_config(tileserver_url=TILESERVER)
        assert VIEW_TYPE in self.allowed(resource, package)


class TestMapViewPage:
    @pytest.fixture(autouse=True)
    def page_request(self, app):
        # Full pages need the language CKAN's WSGI middleware normally puts in
        # the environ, and its before-request hooks; with_request_context has
        # neither, so this class uses its own request context instead.
        flask_app = app.flask_app
        environ = {"CKAN_LANG": "en", "CKAN_LANG_IS_DEFAULT": True, "CKAN_CURRENT_URL": "/"}
        with flask_app.test_request_context("/", environ_overrides=environ):
            flask_app.preprocess_request()
            yield

    def render(self, resource, package):
        plugin = SpatialdataPlugin()
        data_dict = {"resource": resource, "package": package, "resource_view": {}}
        variables = plugin.setup_template_variables({}, data_dict)
        variables.update(resource=resource, package=package, resource_view={})
        return toolkit.render(plugin.view_template({}, data_dict), extra_vars=variables)

    def test_notice_without_tileserver(self, spatialdata_config, monkeypatch, resource, package):
        spatialdata_config(tileserver_url="")

        def no_query(resource_id):
            raise AssertionError("no extent query without a tile server")

        monkeypatch.setattr("ckanext.spatialdata.lib.postgis.resource_extent", no_query)
        html = self.render(resource, package)
        assert "no tile server is configured" in html
        assert 'data-module="spatialdata-map"' not in html
        assert "maplibre" not in html

    def test_map_with_tileserver(self, spatialdata_config, monkeypatch, resource, package):
        spatialdata_config(tileserver_url=TILESERVER)
        monkeypatch.setattr(
            "ckanext.spatialdata.lib.postgis.resource_extent", lambda resource_id: [0, 0, 1, 1]
        )
        html = self.render(resource, package)
        assert 'data-module="spatialdata-map"' in html
        assert f"{TILESERVER}/public.spatialdata_tiles/{{z}}/{{x}}/{{y}}?resource={RESOURCE_ID}" in html
        assert f"/resource/{RESOURCE_ID}/spatialdata/feature/0" in html
        assert "maplibre" in html


class TestMapViewFormPreview:
    """CKAN 2.12.1 can't preview iframed views, so the view form's preview
    of a map view is drawn into the page instead."""

    @pytest.fixture(autouse=True)
    def page_request(self, app):
        flask_app = app.flask_app
        environ = {"CKAN_LANG": "en", "CKAN_LANG_IS_DEFAULT": True, "CKAN_CURRENT_URL": "/"}
        with flask_app.test_request_context("/", environ_overrides=environ):
            flask_app.preprocess_request()
            yield

    @pytest.fixture(autouse=True)
    def extent(self, monkeypatch):
        monkeypatch.setattr(
            "ckanext.spatialdata.lib.postgis.resource_extent", lambda resource_id: [0, 0, 1, 1]
        )

    def render(self, resource, package, resource_view, to_preview=True):
        return toolkit.render_snippet(
            "package/snippets/resource_view.html",
            {
                "resource_view": resource_view,
                "resource": resource,
                "package": package,
                "to_preview": to_preview,
            },
        )

    def view(self, **settings):
        return dict(
            id="view-1", resource_id=RESOURCE_ID, view_type=VIEW_TYPE, title="Map", **settings
        )

    def test_preview_draws_map_inline(self, spatialdata_config, resource, package):
        spatialdata_config(tileserver_url=TILESERVER)
        html = self.render(resource, package, self.view(zoom=13, center_lon=-80, center_lat=40))
        assert "<iframe" not in html
        assert "provide its own iframe" not in html
        assert 'data-module="spatialdata-map"' in html
        assert "spatialdata-map-inline" in html
        assert "data-module-zoom=\"13" in html
        assert f"resource={RESOURCE_ID}" in html

    def test_preview_of_unsaved_view(self, spatialdata_config, resource, package):
        spatialdata_config(tileserver_url=TILESERVER)
        view = self.view()
        del view["id"]
        html = self.render(resource, package, view)
        assert 'data-module="spatialdata-map"' in html
        assert "?view=" not in html

    def test_preview_without_tileserver(self, spatialdata_config, resource, package):
        spatialdata_config(tileserver_url="")
        html = self.render(resource, package, self.view())
        assert "no tile server is configured" in html
        assert "<iframe" not in html

    def test_saved_map_view_still_iframed(self, spatialdata_config, resource, package):
        spatialdata_config(tileserver_url=TILESERVER)
        html = self.render(resource, package, self.view(), to_preview=False)
        assert "<iframe" in html
        assert "spatialdata-map-inline" not in html
