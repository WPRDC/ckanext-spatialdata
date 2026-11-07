# encoding: utf-8
"""Map view style: a list of MapLibre layers drawn from the resource's tiles.

Each layer is a MapLibre style-spec layer without ``id``, ``source`` or
``source-layer``; the map view fills those in, so a style can't point at
other data. https://maplibre.org/maplibre-style-spec/layers/
"""
import json
from typing import Any, Optional

from ckan.plugins import toolkit

ALLOWED_LAYER_TYPES = {"fill", "line", "circle", "symbol", "heatmap", "fill-extrusion"}

# Filled in by the map view for every layer.
MANAGED_KEYS = ("id", "source", "source-layer")

_COLOR = "#1f6feb"


def _geometry_type_is(*types: str) -> list:
    return ["match", ["geometry-type"], list(types), True, False]


# One layer per geometry type, so any geometry (including mixed collections)
# renders.
DEFAULT_LAYERS: list[dict[str, Any]] = [
    {
        "type": "fill",
        "filter": _geometry_type_is("Polygon", "MultiPolygon"),
        "paint": {"fill-color": _COLOR, "fill-opacity": 0.3},
    },
    {
        "type": "line",
        "filter": _geometry_type_is(
            "LineString", "MultiLineString", "Polygon", "MultiPolygon"
        ),
        "paint": {
            "line-color": _COLOR,
            "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1, 16, 2.5],
        },
    },
    {
        "type": "circle",
        "filter": _geometry_type_is("Point", "MultiPoint"),
        "paint": {
            "circle-color": _COLOR,
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 3, 16, 6],
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 1,
        },
    },
]


def dumps(value: Any, indent: int = 0, width: int = 80, offset: int = 0) -> str:
    """JSON with short arrays and objects kept on one line, for the editor.

    Plain ``json.dumps(indent=2)`` puts every element of every expression on
    its own line, which makes styles hard to read. ``offset`` is how much of
    the first line is already used (e.g. by a ``"key": `` prefix).
    """
    compact = json.dumps(value, separators=(", ", ": "))
    if (
        not isinstance(value, (list, dict))
        or not value
        or indent + offset + len(compact) <= width
    ):
        return compact

    pad = " " * (indent + 2)
    if isinstance(value, list):
        items = [pad + dumps(v, indent + 2, width) for v in value]
        open_, close = "[", "]"
    else:
        items = []
        for k, v in value.items():
            key = json.dumps(k) + ": "
            items.append(pad + key + dumps(v, indent + 2, width, len(key)))
        open_, close = "{", "}"
    return open_ + "\n" + ",\n".join(items) + "\n" + " " * indent + close


def parse(value: Any) -> list[dict[str, Any]]:
    """Parse and check a style. Raises ``toolkit.Invalid`` with a readable message."""
    _ = toolkit._
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as e:
            raise toolkit.Invalid(_("Not valid JSON: {error}").format(error=e))

    if not isinstance(value, list) or not value:
        raise toolkit.Invalid(_("The style must be a non-empty list of layers."))

    for i, layer in enumerate(value, start=1):
        if not isinstance(layer, dict):
            raise toolkit.Invalid(
                _("Layer {n} must be an object.").format(n=i)
            )
        if layer.get("type") not in ALLOWED_LAYER_TYPES:
            raise toolkit.Invalid(
                _("Layer {n}: \"type\" must be one of {types}.").format(
                    n=i, types=", ".join(sorted(ALLOWED_LAYER_TYPES))
                )
            )
    return value


def map_style_validator(key, data, errors, context):
    """Validate the view's ``style`` and store it as formatted JSON.

    A style identical to the default isn't stored, so the view keeps
    following the default if it changes.
    """
    value = data.get(key)
    try:
        layers = parse(value)
    except toolkit.Invalid as e:
        errors[key].append(e.error)
        raise toolkit.StopOnError

    if layers == DEFAULT_LAYERS:
        data.pop(key, None)
        raise toolkit.StopOnError
    data[key] = dumps(layers)


def layers_for_view(resource_view: dict) -> tuple[list[dict[str, Any]], Optional[str]]:
    """The layers to draw for a view, and an error message if its style is bad.

    Falls back to the default layers when the view has no style or (e.g. in
    an unsaved preview) an invalid one.
    """
    style = (resource_view or {}).get("style")
    if not style:
        return DEFAULT_LAYERS, None
    try:
        return parse(style), None
    except toolkit.Invalid as e:
        return DEFAULT_LAYERS, e.error
