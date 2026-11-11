"""Georeferencing a resource from another resource's geometries."""
import pytest
from ckan.lib.navl.dictization_functions import Invalid

from ckanext.spatialdata.actions import _georeference_skip_reason
from ckanext.spatialdata.lib.postgis import (
    LINKED_GEOMS_TABLE,
    _has_own_geom_fields,
    linked_geom_type,
    linked_geoms_sql,
    linked_update_sql,
)
from ckanext.spatialdata.lib.util import can_be_spatial, has_geom_link, parse_geom_link
from ckanext.spatialdata.validators import geom_link

pytestmark = pytest.mark.usefixtures("with_request_context")

LINKED = {
    "datastore_active": True,
    "spatialdata_geom_resource": "parcels-id",
    "spatialdata_geom_link": "PARID->PIN",
}


class TestParseGeomLink:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("PARID->PIN", ("PARID", "PIN")),
            (" PARID -> PIN ", ("PARID", "PIN")),
            ("parcel id->PIN", ("parcel id", "PIN")),
        ],
    )
    def test_valid(self, value, expected):
        assert parse_geom_link(value) == expected

    @pytest.mark.parametrize(
        "value", [None, "", "PARID", "PARID->", "->PIN", " -> ", "a->b->c", "PARID-PIN"]
    )
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            parse_geom_link(value)


class TestGeomLinkValidator:
    @pytest.mark.parametrize("value", [None, ""])
    def test_empty(self, value):
        assert geom_link(value) == value

    def test_normalizes_whitespace(self):
        assert geom_link(" PARID -> PIN ") == "PARID->PIN"

    def test_invalid(self):
        with pytest.raises(Invalid):
            geom_link("PARID")


class TestEligibility:
    def test_linked_resource_can_be_spatial(self):
        assert has_geom_link(LINKED)
        assert can_be_spatial(LINKED)
        assert _georeference_skip_reason(LINKED) is None

    @pytest.mark.parametrize(
        "missing", ["spatialdata_geom_resource", "spatialdata_geom_link"]
    )
    def test_link_needs_both_fields(self, missing):
        resource = {k: v for k, v in LINKED.items() if k != missing}
        assert not has_geom_link(resource)
        assert not can_be_spatial(resource)
        assert "linked geometry resource" in _georeference_skip_reason(resource)

    def test_own_fields_take_precedence(self):
        assert not _has_own_geom_fields(LINKED)
        assert _has_own_geom_fields({**LINKED, "spatialdata_wkt_field": "wkt"})


class TestLinkedGeomType:
    @pytest.mark.parametrize(
        "source_type, has_merged, expected",
        [
            ("POLYGON", False, ("POLYGON", "{}")),
            ("POLYGON", True, ("MULTIPOLYGON", "ST_Multi({})")),
            ("POINT", True, ("MULTIPOINT", "ST_Multi({})")),
            ("LINESTRING", True, ("MULTILINESTRING", "ST_Multi({})")),
            ("MULTIPOLYGON", False, ("MULTIPOLYGON", "ST_Multi({})")),
            ("MultiPolygon", True, ("MULTIPOLYGON", "ST_Multi({})")),
            ("GEOMETRYCOLLECTION", True, ("GEOMETRYCOLLECTION", "ST_ForceCollection({})")),
            ("GEOMETRY", True, ("GEOMETRY", "{}")),
            (None, False, ("GEOMETRY", "{}")),
        ],
    )
    def test_types(self, source_type, has_merged, expected):
        assert linked_geom_type(source_type, has_merged) == expected


class TestLinkedSql:
    def test_geoms_sql_unions_only_duplicates(self):
        sql = linked_geoms_sql("parcels-id", "PIN")
        assert f"CREATE TEMP TABLE {LINKED_GEOMS_TABLE}" in sql
        assert 'FROM "parcels-id" g' in sql
        assert 'btrim(g."PIN"::text)' in sql
        assert "WHERE c.n = 1" in sql
        assert "ST_Union(k.geom)" in sql and "WHERE c.n > 1" in sql

    def test_update_sql(self):
        sql = linked_update_sql("assessments-id", "PARID", "ST_Multi({})")
        assert 'UPDATE "assessments-id" AS t' in sql
        # a left join, so unmatched rows are cleared rather than left stale
        assert f"LEFT JOIN {LINKED_GEOMS_TABLE} l" in sql
        assert 'btrim(src."PARID"::text)' in sql
        assert '"_geom" = ST_Multi(l.geom)' in sql
        assert '"_geom_webmercator" = ST_Transform(ST_Multi(l.geom), 3857)' in sql
        assert "src._id > %s AND src._id <= %s" in sql

    def test_identifiers_are_quoted(self):
        sql = linked_update_sql("assessments-id", 'odd"name', "{}")
        assert '"odd""name"' in sql
