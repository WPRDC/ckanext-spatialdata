import json

import pytest
from ckan.lib.navl.dictization_functions import StopOnError
from ckan.plugins import toolkit

from ckanext.spatialdata.lib import map_style
from ckanext.spatialdata.lib.map_style import (
    DEFAULT_LAYERS,
    dumps,
    layers_for_view,
    map_style_validator,
    parse,
)

# toolkit._ needs a request context
pytestmark = pytest.mark.usefixtures("with_request_context")

KEY = ("style",)


def run_validator(value):
    data = {KEY: value}
    errors = {KEY: []}
    stopped = False
    try:
        map_style_validator(KEY, data, errors, {})
    except StopOnError:
        stopped = True
    return data, errors[KEY], stopped


class TestDefaultLayers:
    def test_one_layer_per_geometry_kind(self):
        assert [layer["type"] for layer in DEFAULT_LAYERS] == ["fill", "line", "circle"]

    def test_default_is_valid(self):
        assert parse(DEFAULT_LAYERS) == DEFAULT_LAYERS

    def test_no_managed_keys(self):
        for layer in DEFAULT_LAYERS:
            assert not set(map_style.MANAGED_KEYS) & set(layer)


class TestParse:
    def test_accepts_json_string(self):
        assert parse('[{"type": "fill"}]') == [{"type": "fill"}]

    def test_accepts_list(self):
        assert parse([{"type": "circle"}]) == [{"type": "circle"}]

    @pytest.mark.parametrize("layer_type", sorted(map_style.ALLOWED_LAYER_TYPES))
    def test_allowed_layer_types(self, layer_type):
        parse([{"type": layer_type}])

    @pytest.mark.parametrize(
        "value, message",
        [
            ("[{", "Not valid JSON"),
            ('{"type": "fill"}', "non-empty list of layers"),
            ("[]", "non-empty list of layers"),
            ("null", "non-empty list of layers"),
            ('["fill"]', "Layer 1 must be an object"),
            ('[{"type": "fill"}, {"type": "raster"}]', 'Layer 2: "type" must be one of'),
            ('[{"paint": {}}]', 'Layer 1: "type" must be one of'),
        ],
    )
    def test_rejects(self, value, message):
        with pytest.raises(toolkit.Invalid) as e:
            parse(value)
        assert message in e.value.error


class TestDumps:
    def test_round_trips(self):
        assert json.loads(dumps(DEFAULT_LAYERS)) == DEFAULT_LAYERS

    def test_short_values_stay_on_one_line(self):
        assert dumps({"type": "fill", "paint": {"fill-opacity": 0.3}}) == (
            '{"type": "fill", "paint": {"fill-opacity": 0.3}}'
        )

    def test_long_values_are_expanded(self):
        value = [{"type": "line", "paint": {"line-color": "#" + "a" * 80}}]
        assert dumps(value) == (
            "[\n"
            "  {\n"
            '    "type": "line",\n'
            '    "paint": {\n'
            '      "line-color": "#' + "a" * 80 + '"\n'
            "    }\n"
            "  }\n"
            "]"
        )

    def test_key_width_counts_toward_line_length(self):
        # fits at the top level, but not after a long key
        expression = ["interpolate", ["linear"], ["zoom"], 10, 1, 16, 2.5]
        assert "\n" not in dumps(expression)
        nested = dumps({"a-rather-long-property-name": expression}, indent=10)
        assert "\n" in nested

    def test_empty_containers(self):
        assert dumps([]) == "[]"
        assert dumps({}) == "{}"


class TestMapStyleValidator:
    def test_stores_formatted_style(self):
        data, errors, stopped = run_validator('[{"type":"circle","paint":{"circle-radius":4}}]')
        assert not errors and not stopped
        assert data[KEY] == dumps([{"type": "circle", "paint": {"circle-radius": 4}}])

    def test_default_style_is_not_stored(self):
        data, errors, stopped = run_validator(json.dumps(DEFAULT_LAYERS))
        assert stopped and not errors
        assert KEY not in data

    def test_default_style_matches_regardless_of_formatting(self):
        data, _, _ = run_validator(dumps(DEFAULT_LAYERS))
        assert KEY not in data

    def test_invalid_style_adds_error(self):
        data, errors, stopped = run_validator('[{"type": "raster"}]')
        assert stopped
        assert len(errors) == 1 and "must be one of" in errors[0]
        assert data[KEY] == '[{"type": "raster"}]'


class TestLayersForView:
    @pytest.mark.parametrize("view", [None, {}, {"style": ""}])
    def test_no_style_uses_default(self, view):
        assert layers_for_view(view) == (DEFAULT_LAYERS, None)

    def test_custom_style(self):
        layers = [{"type": "fill", "paint": {"fill-color": "#000"}}]
        assert layers_for_view({"style": json.dumps(layers)}) == (layers, None)

    def test_invalid_style_falls_back_with_error(self):
        # e.g. an unsaved, unvalidated style in a view preview
        layers, error = layers_for_view({"style": "[{"})
        assert layers == DEFAULT_LAYERS
        assert "Not valid JSON" in error
