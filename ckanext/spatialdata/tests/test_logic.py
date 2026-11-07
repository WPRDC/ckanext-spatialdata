"""Validators and action helpers that don't need a database."""
import pytest
from ckan.lib.navl.dictization_functions import Invalid

from ckanext.spatialdata import actions
from ckanext.spatialdata.actions import _add_map_view, _georeference_skip_reason
from ckanext.spatialdata.lib.util import can_be_spatial, out_of_sync
from ckanext.spatialdata.validators import json_object_list

pytestmark = pytest.mark.usefixtures("with_request_context")


class TestJsonObjectList:
    @pytest.mark.parametrize("value", [None, ""])
    def test_empty(self, value):
        assert json_object_list(value) is None

    def test_list_of_objects(self):
        value = [{"id": "name", "type": "text"}]
        assert json_object_list(value) == value

    @pytest.mark.parametrize("value", [{"id": "name"}, "[]", [1, 2], [{"id": "a"}, "b"]])
    def test_invalid(self, value):
        with pytest.raises(Invalid):
            json_object_list(value)


class TestGeoreferenceSkipReason:
    @pytest.mark.parametrize(
        "resource",
        [
            {"format": "GeoJSON"},
            {"format": "geojson", "datastore_active": False},
            {"datastore_active": True, "spatialdata_wkt_field": "geom"},
            {
                "datastore_active": True,
                "spatialdata_latitude_field": "lat",
                "spatialdata_longitude_field": "lng",
            },
        ],
    )
    def test_eligible(self, resource):
        assert _georeference_skip_reason(resource) is None

    def test_not_in_datastore(self):
        reason = _georeference_skip_reason({"format": "CSV", "datastore_active": False})
        assert "not in the datastore" in reason

    @pytest.mark.parametrize(
        "resource",
        [
            {"datastore_active": True},
            # latitude without longitude isn't enough
            {"datastore_active": True, "spatialdata_latitude_field": "lat"},
        ],
    )
    def test_missing_geometry_fields(self, resource):
        assert "No latitude/longitude or WKT field" in _georeference_skip_reason(resource)


class TestSpatialEligibility:
    def test_can_be_spatial(self):
        assert can_be_spatial({"datastore_active": True, "spatialdata_wkt_field": "g"})
        assert not can_be_spatial({"datastore_active": False, "spatialdata_wkt_field": "g"})
        assert not can_be_spatial({"datastore_active": True})

    def test_out_of_sync(self):
        assert out_of_sync({})
        assert out_of_sync(
            {
                "spatialdata_last_geom_updated": "2026-01-01T00:00:00",
                "last_modified": "2026-02-01T00:00:00",
                "metadata_modified": "2026-01-01T00:00:00",
            }
        )
        assert not out_of_sync(
            {
                "spatialdata_last_geom_updated": "2026-03-01T00:00:00",
                "last_modified": "2026-02-01T00:00:00",
                "metadata_modified": "2026-02-01T00:00:00",
            }
        )


class TestAddMapView:
    """_add_map_view runs from the georeferencing hook."""

    @pytest.fixture
    def resource_show(self, monkeypatch):
        resource = {"id": "res-1", "package_id": "pkg-1", "spatialdata_active": True}

        def get_action(name):
            assert name == "resource_show"
            return lambda context, data_dict: resource

        monkeypatch.setattr(actions.toolkit, "get_action", get_action)
        return resource

    def test_creates_map_view(self, monkeypatch, resource_show):
        calls = []

        def add_views(context, resource, view_types=None):
            calls.append((resource["id"], view_types))
            return [{"id": "view-1"}]

        monkeypatch.setattr(actions.datapreview, "add_views_to_resource", add_views)
        _add_map_view({}, "res-1")
        assert calls == [("res-1", ["spatialdata_view"])]

    def test_failure_does_not_raise(self, monkeypatch, resource_show):
        def add_views(context, resource, view_types=None):
            raise RuntimeError("view creation failed")

        monkeypatch.setattr(actions.datapreview, "add_views_to_resource", add_views)
        # must not fail the georeferencing job
        _add_map_view({}, "res-1")
