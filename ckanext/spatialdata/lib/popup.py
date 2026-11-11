# encoding: utf-8
"""Map view popups for a clicked feature.

A resource's ``spatialdata_popup_template`` is Markdown with ``{{ field }}``
placeholders, e.g.::

    **{{ REQUEST_TYPE }}**

    Status: {{ STATUS }}, opened {{ CREATED_ON }}

Placeholders are replaced with the row's values (Markdown-escaped, so data
can't add formatting or links), and the result is rendered with CKAN's
Markdown renderer, which strips raw HTML.
"""
import re
from typing import Any, Optional

from ckan.plugins import toolkit

from ckanext.spatialdata.lib.tiles import INTERNAL_FIELDS

PLACEHOLDER = re.compile(r"\{\{\s*(.+?)\s*\}\}")

# Characters Python-Markdown lets a backslash escape. < and > aren't among
# them, so they (and &) are written as HTML entities instead, which come out
# as text.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!])")


def _escape_markdown(value: str) -> str:
    # newlines would let a value start a new block (heading, list, ...)
    value = " ".join(value.split())
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _MARKDOWN_SPECIAL.sub(r"\\\1", value)


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return toolkit._("Yes") if value else toolkit._("No")
    return str(value)


def fill_template(template: str, record: dict) -> str:
    """The template's Markdown with each ``{{ field }}`` replaced by the
    record's escaped value. Unknown fields become empty."""

    def replace(match: re.Match) -> str:
        return _escape_markdown(format_value(record.get(match.group(1))))

    return PLACEHOLDER.sub(replace, template)


def render_template(template: str, record: dict) -> str:
    """The popup template rendered to sanitized HTML."""
    return toolkit.h.render_markdown(fill_template(template, record), auto_link=False)


def popup_fields(fields: list[dict]) -> list[str]:
    """Columns to list in the default popup: all but internal ones."""
    from ckanext.spatialdata.lib.postgis import GEOM_FIELD, GEOM_MERCATOR_FIELD

    hidden = set(INTERNAL_FIELDS) | {"_id", GEOM_FIELD, GEOM_MERCATOR_FIELD}
    return [f["id"] for f in fields if f["id"] not in hidden]


def popup_vars(resource: dict, record: dict, fields: list[dict]) -> dict:
    """Template variables for spatialdata/snippets/feature_popup.html."""
    title_field = (resource.get("spatialdata_popup_title_field") or "").strip()
    template: Optional[str] = (resource.get("spatialdata_popup_template") or "").strip()
    title = format_value(record.get(title_field)) if title_field else ""
    return {
        "title": title,
        "body": render_template(template, record) if template else None,
        "rows": [
            (name, format_value(record.get(name)))
            for name in popup_fields(fields)
            if name != title_field
        ],
    }
