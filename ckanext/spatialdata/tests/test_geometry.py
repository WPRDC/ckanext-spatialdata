"""Geometry parsing and validation (lib/util.py, lib/geofiles.py)."""
import geojson
import pytest

from ckanext.spatialdata.lib.geofiles import geojson2wkb, validate_geojson_geom, validate_sub_geoms
from ckanext.spatialdata.lib.util import dump_wkb, get_common_geom_type, load_wkb

SQUARE = [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
OTHER_SQUARE = [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
# not closed, so not a valid polygon
OPEN_RING = [[[0, 0], [1, 0], [1, 1], [0, 1]]]


class TestCommonGeomType:
    @pytest.mark.parametrize(
        "values, expected",
        [
            (["POINT (1 2)", "POINT (3 4)"], "POINT"),
            (["POINT (1 2)", "MULTIPOINT ((1 2), (3 4))"], "MULTIPOINT"),
            (["LINESTRING (0 0, 1 1)", "MULTILINESTRING ((0 0, 1 1))"], "MULTILINESTRING"),
            (["POINT (1 2)", "LINESTRING (0 0, 1 1)"], "GEOMETRYCOLLECTION"),
            (
                ["POINT (1 2)", "LINESTRING (0 0, 1 1)", "POLYGON ((0 0, 1 0, 1 1, 0 0))"],
                "GEOMETRYCOLLECTION",
            ),
            (["POINT (1 2)", None], "POINT"),
        ],
    )
    def test_wkt(self, values, expected):
        assert get_common_geom_type(values) == expected

    def test_wkb(self):
        values = [
            dump_wkb({"type": "Polygon", "coordinates": SQUARE}),
            dump_wkb({"type": "MultiPolygon", "coordinates": [SQUARE]}),
        ]
        assert get_common_geom_type(values, geom_format="wkb") == "MULTIPOLYGON"

    def test_no_values(self):
        with pytest.raises(TypeError):
            get_common_geom_type([None])


class TestLoadWkb:
    def test_bytes(self):
        point = {"type": "Point", "coordinates": [1.0, 2.0]}
        assert load_wkb(dump_wkb(point)) == point

    def test_postgres_hex_string(self):
        # bytea read back as text: "\x" followed by hex
        point = {"type": "Point", "coordinates": [1.0, 2.0]}
        assert load_wkb("\\x" + dump_wkb(point).hex()) == point


class TestValidateSubGeoms:
    def test_keeps_only_valid_parts(self):
        result = validate_sub_geoms(geojson.MultiPolygon, geojson.Polygon, [SQUARE, OPEN_RING])
        assert result["coordinates"] == [SQUARE]

    def test_all_valid(self):
        result = validate_sub_geoms(geojson.MultiPolygon, geojson.Polygon, [SQUARE, OTHER_SQUARE])
        assert result["coordinates"] == [SQUARE, OTHER_SQUARE]

    def test_none_valid(self):
        assert validate_sub_geoms(geojson.MultiPolygon, geojson.Polygon, [OPEN_RING]) is None


class TestValidateGeojsonGeom:
    @pytest.mark.parametrize(
        "geometry",
        [
            {"type": "Point", "coordinates": [1, 2]},
            {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            {"type": "Polygon", "coordinates": SQUARE},
            {"type": "MultiPoint", "coordinates": [[1, 2], [3, 4]]},
            {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]]]},
            {"type": "MultiPolygon", "coordinates": [SQUARE]},
        ],
    )
    def test_valid(self, geometry):
        assert validate_geojson_geom(geometry) is not None

    def test_invalid_polygon(self):
        assert validate_geojson_geom({"type": "Polygon", "coordinates": OPEN_RING}) is None

    def test_multipolygon_with_one_bad_part(self):
        result = validate_geojson_geom({"type": "MultiPolygon", "coordinates": [SQUARE, OPEN_RING]})
        assert result["coordinates"] == [SQUARE]

    def test_unsupported_type(self):
        assert validate_geojson_geom({"type": "GeometryCollection", "geometries": []}) is None


class TestGeojson2Wkb:
    def test_valid(self):
        wkb_value = geojson2wkb({"type": "Point", "coordinates": [1, 2]})
        assert load_wkb(wkb_value)["coordinates"] == [1.0, 2.0]

    def test_invalid(self):
        assert geojson2wkb({"type": "Polygon", "coordinates": OPEN_RING}) is None
