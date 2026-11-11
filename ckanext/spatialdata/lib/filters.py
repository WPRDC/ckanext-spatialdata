# encoding: utf-8
"""Map view filters: limit the rows a map view draws.

A view's ``filters`` is a JSON list of ``{"field", "op", "value"}`` objects,
all of which must match (AND). They're sent to the tile function
(tile_function.sql) in the tile URL's ``filters`` parameter, and the function
builds its WHERE clause from them without putting any of their text into the
SQL: field names must be columns of the table and are quoted, operators come
from a fixed list, and values are passed as query parameters and cast to the
column's type.

Filters only narrow what a map shows. Anyone can request tiles without them,
so they are not a way to hide data.

The limits and operators here must match tile_function.sql.
"""
import datetime
import json
import re
from typing import Any, Optional

from ckan.plugins import toolkit

MAX_FILTERS = 10
MAX_LIST_VALUES = 100
MAX_VALUE_LENGTH = 500

# How an operator takes its value.
NO_VALUE = "none"
SINGLE = "single"
LIST = "list"
INTERVAL = "interval"

# op: (value kind, label). Order is the order offered in the form.
OPERATORS: dict[str, tuple[str, str]] = {
    "=": (SINGLE, "equals"),
    "!=": (SINGLE, "does not equal"),
    "in": (LIST, "is one of"),
    "not in": (LIST, "is not one of"),
    "contains": (SINGLE, "contains"),
    "<": (SINGLE, "is less than / before"),
    "<=": (SINGLE, "is at most / on or before"),
    ">": (SINGLE, "is greater than / after"),
    ">=": (SINGLE, "is at least / on or after"),
    "last": (INTERVAL, "is in the last"),
    "empty": (NO_VALUE, "is empty"),
    "not empty": (NO_VALUE, "is not empty"),
}

# Operators whose value is cast to the column's type.
TYPED_OPERATORS = {"=", "!=", "in", "not in", "<", "<=", ">", ">="}

INTERVAL_UNITS = ("minute", "hour", "day", "week", "month", "year")
# e.g. "1 year", "30 days". Must match the check in tile_function.sql.
INTERVAL_RE = re.compile(r"^(\d{1,4}) (" + "|".join(INTERVAL_UNITS) + r")s?$")

# datastore type names (as datastore_info reports them)
DATE_TYPES = {"date", "timestamp", "timestamptz"}
NUMBER_TYPES = {
    "int", "int2", "int4", "int8", "integer", "bigint", "smallint",
    "numeric", "float", "float4", "float8", "real", "double precision",
}
BOOL_TYPES = {"bool", "boolean"}

# Columns the tile function won't filter on (plus the geometry columns; see
# _unfilterable_fields).
INTERNAL_FIELDS = {"_full_text", "spatialdata_wkb"}


def _unfilterable_fields() -> set[str]:
    # imported here: lib.postgis imports the datastore backend
    from ckanext.spatialdata.lib.postgis import GEOM_FIELD, GEOM_MERCATOR_FIELD

    return INTERNAL_FIELDS | {GEOM_FIELD, GEOM_MERCATOR_FIELD}


def is_array_type(type_name: str) -> bool:
    return type_name.startswith("_") or type_name.endswith("[]")


def operators_for_form() -> list[dict[str, str]]:
    """The operators, for the view form's filter editor."""
    return [
        {"op": op, "label": toolkit._(label), "value": kind}
        for op, (kind, label) in OPERATORS.items()
    ]


def normalize_interval(value: Any) -> str:
    """``" 30  Days "`` → ``"30 days"``. Raises ValueError if it isn't one."""
    text = " ".join(str(value).lower().split())
    match = INTERVAL_RE.match(text)
    if not match:
        raise ValueError(
            toolkit._(
                'Use a number and a unit, like "1 year" or "30 days" '
                "(units: {units})."
            ).format(units=", ".join(INTERVAL_UNITS))
        )
    number, unit = match.groups()
    number = int(number)
    return f"{number} {unit}{'' if number == 1 else 's'}"


def _check_typed_value(value: str, type_name: str) -> None:
    _ = toolkit._
    if type_name in NUMBER_TYPES:
        try:
            float(value)
        except ValueError:
            raise ValueError(_('"{value}" is not a number.').format(value=value))
    elif type_name in DATE_TYPES:
        try:
            datetime.datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(
                _('"{value}" is not a date; use a date like 2025-01-31.').format(
                    value=value
                )
            )
    elif type_name in BOOL_TYPES:
        if value.lower() not in ("true", "false"):
            raise ValueError(_('"{value}" must be true or false.').format(value=value))


def _value_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)) or value is None:
        raise ValueError(toolkit._("A value must be text or a number."))
    text = str(value).strip()
    if len(text) > MAX_VALUE_LENGTH:
        raise ValueError(
            toolkit._("Values can be at most {n} characters.").format(
                n=MAX_VALUE_LENGTH
            )
        )
    return text


def _clean_filter(item: Any, field_types: Optional[dict[str, str]]) -> dict[str, Any]:
    _ = toolkit._
    if not isinstance(item, dict):
        raise ValueError(_("Each filter must be an object."))
    field = item.get("field")
    op = item.get("op")
    if not isinstance(field, str) or not field.strip():
        raise ValueError(_("Choose a field."))
    field = field.strip()
    if op not in OPERATORS:
        raise ValueError(
            _('"{op}" is not an operator. Use one of: {ops}.').format(
                op=op, ops=", ".join(OPERATORS)
            )
        )
    if field in _unfilterable_fields():
        raise ValueError(_('Can\'t filter on "{field}".').format(field=field))

    type_name = None
    if field_types is not None:
        if field not in field_types:
            raise ValueError(_('"{field}" is not a field of this table.').format(field=field))
        type_name = field_types[field]

    kind = OPERATORS[op][0]
    if type_name and is_array_type(type_name) and op in TYPED_OPERATORS | {"last"}:
        raise ValueError(
            _('"{field}" is a list field; use "contains", "is empty" or "is not empty".').format(
                field=field
            )
        )
    if kind == INTERVAL and type_name and type_name not in DATE_TYPES:
        raise ValueError(
            _('"is in the last" needs a date or timestamp field; "{field}" is {type}.').format(
                field=field, type=type_name
            )
        )

    cleaned: dict[str, Any] = {"field": field, "op": op}
    value = item.get("value")
    if kind == NO_VALUE:
        return cleaned
    if kind == INTERVAL:
        cleaned["value"] = normalize_interval(value)
        return cleaned
    if kind == LIST:
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, list):
            raise ValueError(_("Give a list of values."))
        values = []
        for v in value:
            text = _value_text(v)
            if text and text not in values:
                values.append(text)
        if not values:
            raise ValueError(_("Give at least one value."))
        if len(values) > MAX_LIST_VALUES:
            raise ValueError(
                _("A list can have at most {n} values.").format(n=MAX_LIST_VALUES)
            )
        if type_name:
            for text in values:
                _check_typed_value(text, type_name)
        cleaned["value"] = values
        return cleaned

    text = _value_text(value)
    if text == "":
        raise ValueError(_("Give a value."))
    if type_name and op in TYPED_OPERATORS:
        _check_typed_value(text, type_name)
    cleaned["value"] = text
    return cleaned


def parse(value: Any, field_types: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
    """Check filters (a JSON string or a list) and return them normalized.

    :param field_types: the table's ``{field: datastore type}``, to check
        fields and values against; skipped when None.
    Raises ``toolkit.Invalid`` with a readable message.
    """
    _ = toolkit._
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as e:
            raise toolkit.Invalid(_("Not valid JSON: {error}").format(error=e))
    if not isinstance(value, list):
        raise toolkit.Invalid(_("Filters must be a list."))
    if len(value) > MAX_FILTERS:
        raise toolkit.Invalid(_("At most {n} filters.").format(n=MAX_FILTERS))

    cleaned = []
    for i, item in enumerate(value, start=1):
        try:
            cleaned.append(_clean_filter(item, field_types))
        except ValueError as e:
            raise toolkit.Invalid(_("Filter {n}: {error}").format(n=i, error=e))
    return cleaned


def dumps(filters: list[dict[str, Any]]) -> str:
    """Compact JSON, as stored on the view and sent in tile URLs."""
    return json.dumps(filters, separators=(",", ":"), ensure_ascii=False)


def _field_types(resource_id: Any) -> Optional[dict[str, str]]:
    if not resource_id or not isinstance(resource_id, str):
        return None
    try:
        info = toolkit.get_action("datastore_info")(
            {"ignore_auth": True}, {"id": resource_id}
        )
    except Exception:
        return None
    return {f["id"]: f.get("type") or "" for f in info.get("fields", [])}


def filters_validator(key, data, errors, context):
    """Validate the view's ``filters`` against its table and store them as
    compact JSON (or not at all, when there are none)."""
    try:
        filters = parse(data.get(key), _field_types(data.get(("resource_id",))))
    except toolkit.Invalid as e:
        errors[key].append(e.error)
        raise toolkit.StopOnError
    if not filters:
        data.pop(key, None)
        raise toolkit.StopOnError
    data[key] = dumps(filters)


def filters_for_view(resource_view: dict) -> tuple[list[dict[str, Any]], Optional[str]]:
    """A view's filters, and an error message if they're bad (e.g. in an
    unsaved preview). Bad filters draw nothing rather than everything."""
    try:
        return parse((resource_view or {}).get("filters")), None
    except toolkit.Invalid as e:
        return [], e.error


def describe(filters: list[dict[str, Any]]) -> str:
    """A short description for the map, e.g. ``status is one of Open, New``."""
    parts = []
    for f in filters:
        kind, label = OPERATORS[f["op"]]
        label = toolkit._(label).split(" / ")[0]
        value = f.get("value")
        if kind == LIST:
            value = ", ".join(value)
        parts.append(f"{f['field']} {label}" + (f" {value}" if kind != NO_VALUE else ""))
    return "; ".join(parts)
