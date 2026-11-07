import pytest

from ckanext.spatialdata.helpers import (
    spatialdata_package_is_processed,
    spatialdata_processed_resources,
    spatialdata_status_description,
    spatialdata_tile_source,
)

RESOURCE_ID = "09900a13-ab5d-4e41-94f8-7e4d129e9a4c"

pytestmark = pytest.mark.usefixtures("with_request_context")


class TestTileSource:
    def test_tilejson_url(self, spatialdata_config):
        spatialdata_config(
            tileserver_url="https://tiles.example.org",
            tile_source_id_format="table.{table}.{column}",
        )
        assert spatialdata_tile_source(RESOURCE_ID) == {
            "source_id": f"table.{RESOURCE_ID}._geom",
            "tilejson_url": f"https://tiles.example.org/table.{RESOURCE_ID}._geom",
        }

    def test_trailing_slash_is_dropped(self, spatialdata_config):
        spatialdata_config(tileserver_url="https://tiles.example.org/")
        url = spatialdata_tile_source(RESOURCE_ID)["tilejson_url"]
        assert url.startswith("https://tiles.example.org/table.")
        assert "//table" not in url

    def test_custom_source_id_format(self, spatialdata_config):
        spatialdata_config(
            tileserver_url="https://tiles.example.org",
            tile_source_id_format="{schema}.{table}.{column}",
        )
        assert spatialdata_tile_source(RESOURCE_ID)["source_id"] == (
            f"public.{RESOURCE_ID}._geom"
        )

    def test_no_tileserver(self, spatialdata_config):
        spatialdata_config(tileserver_url="")
        source = spatialdata_tile_source(RESOURCE_ID)
        assert source["tilejson_url"] is None
        # the layer name is still known
        assert source["source_id"] == f"table.{RESOURCE_ID}._geom"


class TestPackageIsProcessed:
    @pytest.mark.parametrize(
        "resources, expected",
        [
            ([], False),
            ([{"spatialdata_active": False}], False),
            ([{}, {"spatialdata_active": True}], True),
            ([{"spatialdata_active": "true"}], True),
            (None, False),
        ],
    )
    def test_any_active_resource(self, resources, expected):
        assert spatialdata_package_is_processed({"resources": resources}) is expected


class TestProcessedResources:
    def test_only_active_resources(self, spatialdata_config):
        spatialdata_config(tileserver_url="https://tiles.example.org")
        pkg = {
            "resources": [
                {"id": RESOURCE_ID, "name": "Boundary", "spatialdata_active": True},
                {"id": "other", "name": "CSV", "spatialdata_active": False},
            ]
        }
        resources = spatialdata_processed_resources(pkg)

        assert [r["id"] for r in resources] == [RESOURCE_ID]
        resource = resources[0]
        assert resource["name"] == "Boundary"
        assert f'FROM "{RESOURCE_ID}"' in resource["sql"]
        assert "ST_Intersects" in resource["sql"]
        assert "datastore_search_sql" in resource["sql_api_url"]
        assert resource["tilejson_url"] == (
            f"https://tiles.example.org/table.{RESOURCE_ID}._geom"
        )


class TestStatusDescription:
    @pytest.mark.parametrize(
        "status, expected",
        [
            ("COMPLETE", "Complete"),
            ("ERROR", "Error"),
            ("NOT_STARTED", "Not georeferenced"),
            ("SOMETHING_NEW", "SOMETHING_NEW"),
            (None, "Not Uploaded Yet"),
        ],
    )
    def test_captions(self, status, expected):
        assert spatialdata_status_description({"status": status}) == expected
