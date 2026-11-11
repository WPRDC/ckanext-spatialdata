"""Map view tiles with chosen fields, hover/click popups and their metadata."""
from types import SimpleNamespace

import pytest
from ckan.lib.navl.dictization_functions import StopOnError, missing

from ckanext.spatialdata import validators
from ckanext.spatialdata.lib import popup, tiles

pytestmark = pytest.mark.usefixtures("with_request_context")

RESOURCE_ID = "09900a13-ab5d-4e41-94f8-7e4d129e9a4c"


class TestFieldLists:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, []),
            ("", []),
            ("a", ["a"]),
            (" a , b,,a ,c ", ["a", "b", "c"]),
            (["a", " b", "a"], ["a", "b"]),
            ("REQUEST TYPE, STATUS", ["REQUEST TYPE", "STATUS"]),
        ],
    )
    def test_parse(self, value, expected):
        assert tiles.parse_field_list(value) == expected

    @pytest.mark.parametrize("value", [None, ""])
    def test_validator_empty(self, value):
        assert validators.field_list(value) == value

    def test_validator_normalizes(self):
        assert validators.field_list(" STATUS ,, CREATED_ON, STATUS") == "STATUS,CREATED_ON"


class TestStyleFields:
    def test_finds_get_and_has(self):
        layers = [
            {"type": "circle", "paint": {"circle-color": [
                "match", ["get", "STATUS"], "Open", "#f00", "#00f"]}},
            {"type": "symbol", "filter": ["has", "LABEL"],
             "layout": {"text-field": ["get", "LABEL"]}},
        ]
        assert tiles.style_fields(layers) == ["STATUS", "LABEL"]

    def test_ignores_other_expressions(self):
        layers = [{"type": "fill", "filter": ["==", ["geometry-type"], "Polygon"],
                   "paint": {"fill-color": "#000", "fill-opacity": ["get", 3]}}]
        assert tiles.style_fields(layers) == []


class TestTileFields:
    def test_combines_hover_title_and_style(self):
        resource = {
            "spatialdata_tile_fields": "STATUS,CREATED_ON",
            "spatialdata_popup_title_field": " REQUEST_TYPE ",
        }
        layers = [{"type": "circle", "paint": {"circle-color": ["get", "STATUS"]},
                   "filter": ["has", "_full_text"]}]
        assert tiles.tile_fields(resource, layers) == [
            "STATUS", "CREATED_ON", "REQUEST_TYPE"
        ]

    def test_nothing_configured(self):
        assert tiles.tile_fields({}) == []


class TestTileUrl:
    def test_without_tileserver(self, spatialdata_config):
        spatialdata_config(tileserver_url="")
        assert tiles.tile_url_template(RESOURCE_ID, ["a"]) is None

    def test_url(self, spatialdata_config):
        spatialdata_config(tileserver_url="https://example.org/tiles/")
        assert tiles.tile_url_template(RESOURCE_ID, ["a b", "c"], "2026-01-01T00:00") == (
            "https://example.org/tiles/public.spatialdata_tiles/{z}/{x}/{y}"
            f"?resource={RESOURCE_ID}&fields=a+b%2Cc&v=2026-01-01T00%3A00"
        )

    def test_custom_source(self, spatialdata_config):
        spatialdata_config(
            tileserver_url="https://example.org", tile_function_source="tiles.fn"
        )
        assert tiles.tile_url_template(RESOURCE_ID, []) == (
            f"https://example.org/tiles.fn/{{z}}/{{x}}/{{y}}?resource={RESOURCE_ID}"
        )


class TestTileFunctionSql:
    def test_placeholders_filled(self):
        sql = tiles.tile_function_sql()
        assert "CREATE OR REPLACE FUNCTION public.spatialdata_tiles" in sql
        assert "ST_AsMVT(t, 'features'" in sql
        assert '"_geom_webmercator"' in sql
        for placeholder in ("{layer}", "{geom_field}", "{mercator_field}"):
            assert placeholder not in sql
        # other braces in the SQL are left alone
        assert "{z}/{x}/{y}" in sql


class TestPopupTemplate:
    def test_fills_fields(self):
        record = {"TYPE": "Potholes", "COUNT": 3, "OPEN": True, "NOTE": None}
        assert popup.fill_template(
            "{{TYPE}}: {{ COUNT }} ({{ OPEN }}){{ NOTE }}{{ missing }}", record
        ) == "Potholes: 3 (Yes)"

    def test_field_names_with_spaces(self):
        assert popup.fill_template("{{ REQUEST TYPE }}", {"REQUEST TYPE": "x"}) == "x"

    def test_values_are_escaped(self):
        value = "**bold** [link](javascript:alert(1)) <b>x</b> & #h\nnext"
        filled = popup.fill_template("{{ v }}", {"v": value})
        assert filled == (
            "\\*\\*bold\\*\\* \\[link\\]\\(javascript:alert\\(1\\)\\) "
            "&lt;b&gt;x&lt;/b&gt; &amp; \\#h next"
        )

    def test_render_sanitizes(self):
        html = popup.render_template(
            "**{{ t }}** <script>alert(1)</script>\n\n> {{ d }}",
            {"t": "Potholes", "d": "<img src=x onerror=alert(2)> [x](javascript:1)"},
        )
        assert "<strong>Potholes</strong>" in html
        assert "<script" not in html and "<img" not in html
        assert "href" not in html
        assert "&lt;img src=x onerror=alert(2)&gt;" in html

    def test_popup_vars_with_template(self):
        resource = {
            "spatialdata_popup_title_field": "TYPE",
            "spatialdata_popup_template": "Status: {{ STATUS }}",
        }
        variables = popup.popup_vars(resource, {"TYPE": "Potholes", "STATUS": "Open"}, [])
        assert variables["title"] == "Potholes"
        assert "Status: Open" in variables["body"]

    def test_popup_vars_lists_fields_without_template(self):
        fields = [{"id": f} for f in
                  ("_id", "TYPE", "STATUS", "_geom", "_geom_webmercator", "_full_text")]
        variables = popup.popup_vars(
            {"spatialdata_popup_title_field": "TYPE"},
            {"_id": 1, "TYPE": "Potholes", "STATUS": "Open"},
            fields,
        )
        assert variables["body"] is None
        assert variables["rows"] == [("STATUS", "Open")]


class TestSysadminOnly:
    KEY = ("resources", 0, "spatialdata_tile_fields")

    @pytest.fixture
    def stored(self, monkeypatch):
        """Stub the saved resource: {"spatialdata_tile_fields": "SAVED"}."""
        from ckan import model

        saved = SimpleNamespace(
            package_id="pkg-1", extras={"spatialdata_tile_fields": "SAVED"}
        )
        monkeypatch.setattr(
            model.Resource, "get", staticmethod(lambda id: saved if id == "res-1" else None)
        )

    @pytest.fixture
    def sysadmin(self, monkeypatch):
        names = set()
        monkeypatch.setattr(validators.authz, "is_sysadmin", lambda user: user in names)
        return names

    def run(self, value, user="editor", resource_id="res-1", **context):
        data = {self.KEY: value, ("resources", 0, "id"): resource_id}
        context = {"user": user, **context}
        try:
            validators.sysadmin_only(self.KEY, data, {}, context)
        except StopOnError:
            pass
        return data.get(self.KEY, "<dropped>")

    def test_sysadmin_sets(self, stored, sysadmin):
        sysadmin.add("admin")
        assert self.run("NEW", user="admin") == "NEW"
        assert self.run("", user="admin") == ""

    def test_ignore_auth_sets(self, stored, sysadmin):
        assert self.run("NEW", ignore_auth=True) == "NEW"

    def test_non_sysadmin_keeps_saved(self, stored, sysadmin):
        assert self.run("NEW") == "SAVED"
        assert self.run("") == "SAVED"

    def test_missing_keeps_saved_even_for_sysadmin(self, stored, sysadmin):
        sysadmin.add("admin")
        assert self.run(missing, user="admin") == "SAVED"

    def test_new_resource_drops(self, stored, sysadmin):
        assert self.run("NEW", resource_id=missing) == "<dropped>"
        assert self.run("NEW", resource_id="other") == "<dropped>"

    def test_resource_of_another_dataset_drops(self, stored, sysadmin):
        package = SimpleNamespace(id="pkg-2")
        assert self.run("NEW", package=package) == "<dropped>"
