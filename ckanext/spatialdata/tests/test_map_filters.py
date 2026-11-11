"""Map view filters (lib/filters.py) and starting position validators."""
import json

import pytest
from ckan.lib.navl.dictization_functions import Invalid, StopOnError, missing
from ckan.plugins import toolkit

from ckanext.spatialdata.lib import filters as map_filters
from ckanext.spatialdata.lib import tiles
from ckanext.spatialdata.validators import both_or_neither, number_in_range

# toolkit._ needs a request context
pytestmark = pytest.mark.usefixtures("with_request_context")

RESOURCE_ID = "09900a13-ab5d-4e41-94f8-7e4d129e9a4c"
TYPES = {
    "STATUS": "text",
    "REQUEST_ID": "int4",
    "CREATED_ON": "timestamp",
    "TAGS": "_text",
}


def parse(value, types=TYPES):
    return map_filters.parse(value, types)


class TestParse:
    def test_empty(self):
        assert parse(None) == []
        assert parse("") == []
        assert parse("[]") == []

    def test_normalizes(self):
        value = json.dumps([
            {"field": " STATUS ", "op": "in", "value": "Open, New,,Open"},
            {"field": "CREATED_ON", "op": "last", "value": " 1  Years "},
            {"field": "CREATED_ON", "op": "last", "value": "30 day"},
            {"field": "REQUEST_ID", "op": ">=", "value": 100},
            {"field": "STATUS", "op": "empty", "value": "ignored"},
            {"field": "TAGS", "op": "contains", "value": "x"},
        ])
        assert parse(value) == [
            {"field": "STATUS", "op": "in", "value": ["Open", "New"]},
            {"field": "CREATED_ON", "op": "last", "value": "1 year"},
            {"field": "CREATED_ON", "op": "last", "value": "30 days"},
            {"field": "REQUEST_ID", "op": ">=", "value": "100"},
            {"field": "STATUS", "op": "empty"},
            {"field": "TAGS", "op": "contains", "value": "x"},
        ]

    def test_without_types_skips_field_checks(self):
        assert parse([{"field": "ANY", "op": "=", "value": "x"}], None) == [
            {"field": "ANY", "op": "=", "value": "x"}
        ]

    @pytest.mark.parametrize(
        "value, message",
        [
            ("[{", "Not valid JSON"),
            ('{"field": "STATUS"}', "must be a list"),
            ([{"field": "STATUS", "op": "empty"}] * 11, "At most 10"),
            (["STATUS"], "must be an object"),
            ([{"op": "="}], "Choose a field"),
            ([{"field": "STATUS", "op": "LIKE", "value": "x"}], "is not an operator"),
            ([{"field": "NOPE", "op": "=", "value": "x"}], "not a field of this table"),
            ([{"field": "_full_text", "op": "contains", "value": "x"}], "Can't filter"),
            ([{"field": "_geom", "op": "empty"}], "Can't filter"),
            ([{"field": "STATUS", "op": "=", "value": ""}], "Give a value"),
            ([{"field": "STATUS", "op": "=", "value": ["a"]}], "text or a number"),
            ([{"field": "STATUS", "op": "in", "value": []}], "at least one value"),
            ([{"field": "STATUS", "op": "in", "value": [str(i) for i in range(101)]}], "at most 100"),
            ([{"field": "STATUS", "op": "=", "value": "x" * 501}], "at most 500"),
            ([{"field": "REQUEST_ID", "op": "=", "value": "1 OR 1=1"}], "is not a number"),
            ([{"field": "REQUEST_ID", "op": "in", "value": ["1", "two"]}], "is not a number"),
            ([{"field": "CREATED_ON", "op": ">=", "value": "last tuesday"}], "is not a date"),
            ([{"field": "CREATED_ON", "op": "last", "value": "1 decade"}], "number and a unit"),
            ([{"field": "CREATED_ON", "op": "last", "value": "1 year; DROP"}], "number and a unit"),
            ([{"field": "STATUS", "op": "last", "value": "1 year"}], "date or timestamp"),
            ([{"field": "TAGS", "op": "=", "value": "x"}], "list field"),
        ],
    )
    def test_rejects(self, value, message):
        with pytest.raises(toolkit.Invalid) as e:
            parse(value)
        assert message in e.value.error

    def test_error_names_the_filter(self):
        with pytest.raises(toolkit.Invalid) as e:
            parse([{"field": "STATUS", "op": "empty"}, {"field": "NOPE", "op": "empty"}])
        assert e.value.error.startswith("Filter 2:")


class TestValidator:
    @pytest.fixture
    def datastore_info(self, monkeypatch):
        calls = []

        def action(context, data_dict):
            calls.append(data_dict["id"])
            return {"fields": [{"id": k, "type": v} for k, v in TYPES.items()]}

        monkeypatch.setattr(
            toolkit, "get_action", lambda name: action if name == "datastore_info" else None
        )
        return calls

    def run(self, value):
        key = ("filters",)
        data = {key: value, ("resource_id",): RESOURCE_ID}
        errors = {key: []}
        stopped = False
        try:
            map_filters.filters_validator(key, data, errors, {})
        except StopOnError:
            stopped = True
        return data.get(key), errors[key], stopped

    def test_stores_compact_json(self, datastore_info):
        value, errors, _ = self.run('[{"field": "STATUS", "op": "in", "value": "A, B"}]')
        assert value == '[{"field":"STATUS","op":"in","value":["A","B"]}]'
        assert errors == []
        assert datastore_info == [RESOURCE_ID]

    def test_checks_against_the_table(self, datastore_info):
        value, errors, stopped = self.run('[{"field": "NOPE", "op": "empty"}]')
        assert stopped and "not a field" in errors[0]

    def test_empty_list_not_stored(self, datastore_info):
        value, errors, stopped = self.run("[]")
        assert value is None and stopped and errors == []


class TestForView:
    def test_bad_filters_report_error(self):
        filters, error = map_filters.filters_for_view({"filters": "[{"})
        assert filters == [] and "Not valid JSON" in error

    def test_describe(self):
        assert map_filters.describe([
            {"field": "CREATED_ON", "op": "last", "value": "1 year"},
            {"field": "STATUS", "op": "in", "value": ["Open", "New"]},
            {"field": "REQUEST_ID", "op": ">=", "value": "5"},
            {"field": "DEPT", "op": "not empty"},
        ]) == (
            "CREATED_ON is in the last 1 year; STATUS is one of Open, New; "
            "REQUEST_ID is at least 5; DEPT is not empty"
        )

    def test_operators_for_form(self):
        ops = map_filters.operators_for_form()
        assert [o["op"] for o in ops] == list(map_filters.OPERATORS)
        assert {"op": "last", "label": "is in the last", "value": "interval"} in ops


class TestOperatorsMatchSql:
    def test_sql_knows_every_operator(self):
        sql = tiles.tile_function_sql()
        for op in map_filters.OPERATORS:
            assert f"WHEN '{op}'" in sql
        assert "jsonb_array_length(filters) > 10" in sql
        assert str(map_filters.MAX_FILTERS) == "10"
        assert "> 100" in sql and map_filters.MAX_LIST_VALUES == 100
        for unit in map_filters.INTERVAL_UNITS:
            assert unit in sql


class TestTileUrl:
    def test_filters_in_url(self, spatialdata_config):
        spatialdata_config(tileserver_url="https://example.org")
        url = tiles.tile_url_template(
            RESOURCE_ID, [], None, '[{"field":"A","op":"empty"}]'
        )
        assert url.endswith(
            "&filters=%5B%7B%22field%22%3A%22A%22%2C%22op%22%3A%22empty%22%7D%5D"
        )


class TestPositionValidators:
    @pytest.mark.parametrize("value, expected", [("-79.99", -79.99), (12, 12.0), ("0", 0.0)])
    def test_number_in_range(self, value, expected):
        assert number_in_range(-180, 180)(value) == expected

    @pytest.mark.parametrize("value", ["abc", "181", None])
    def test_number_out_of_range(self, value):
        with pytest.raises(Invalid):
            number_in_range(-180, 180)(value)

    @pytest.mark.parametrize(
        "this, other, ok",
        [("1", "2", True), ("", "", True), (missing, missing, True),
         ("1", "", False), ("1", missing, False), ("", "2", True)],
    )
    def test_both_or_neither(self, this, other, ok):
        key = ("center_lon",)
        data = {key: this, ("center_lat",): other}
        errors = {key: []}
        validator = both_or_neither("center_lat", "latitude")
        if ok:
            validator(key, data, errors, {})
            assert errors[key] == []
        else:
            with pytest.raises(StopOnError):
                validator(key, data, errors, {})
            assert errors[key] == ["Also set the latitude."]
