/* Map view settings form (spatialdata_view_form.html): the starting
 * position and the filter editor.
 */

/* Starting position: fills the longitude, latitude and zoom inputs from the
 * preview map, which spatialdata-map.js leaves on window.spatialdataMap: this
 * page's own (the form's preview is drawn into the page), or an iframe's.
 */
ckan.module("spatialdata-view-position", function ($) {
  return {
    initialize: function () {
      $.proxyAll(this, /_on/);
      this.status = this.el.find("[data-position-status]");
      this.el.find("[data-position-use]").on("click", this._onUse);
      this.el.find("[data-position-clear]").on("click", this._onClear);
    },

    _previewMap: function () {
      var map = window.spatialdataMap || null;
      if (map) {
        return map;
      }
      $("iframe").each(function () {
        try {
          // same origin; a cross-origin frame throws, and is skipped
          if (this.contentWindow && this.contentWindow.spatialdataMap) {
            map = this.contentWindow.spatialdataMap;
            return false;
          }
        } catch (e) {
          // not ours
        }
      });
      return map;
    },

    _onUse: function () {
      var map = this._previewMap();
      if (!map) {
        this.status.text(this._("Click Preview first, then move the map."));
        return;
      }
      var center = map.getCenter();
      this.el.find("[name=center_lon]").val(center.lng.toFixed(5));
      this.el.find("[name=center_lat]").val(center.lat.toFixed(5));
      this.el.find("[name=zoom]").val(Math.round(map.getZoom() * 100) / 100);
      this.status.text(this._("Position set. Save to keep it."));
    },

    _onClear: function () {
      this.el.find("[name=center_lon], [name=center_lat], [name=zoom]").val("");
      this.status.text("");
    },
  };
});

/* Filters: rows of field / operator / value, written to the `filters`
 * textarea as JSON (see lib/filters.py, which checks them again on save).
 * If the textarea holds JSON that can't be shown as rows, it's left as a
 * plain textarea to fix by hand.
 *
 * Options:
 *   fields    - the table's fields, [{id, type}, ...]
 *   operators - [{op, label, value: "none"|"single"|"list"|"interval"}, ...]
 */
ckan.module("spatialdata-filter-editor", function ($) {
  // must match DATE_TYPES in lib/filters.py
  var DATE_TYPES = ["date", "timestamp", "timestamptz"];
  // operators that compare with the column's type; not for list columns
  var TYPED_OPS = ["=", "!=", "in", "not in", "<", "<=", ">", ">=", "last"];

  function isArrayType(type) {
    type = type || "";
    return type.charAt(0) === "_" || type.slice(-2) === "[]";
  }

  return {
    options: {
      fields: [],
      operators: [],
    },

    initialize: function () {
      $.proxyAll(this, /_on/);
      this.textarea = this.el.find("textarea[name=filters]");
      this.rows = this.el.find("[data-filter-rows]");
      this.types = {};
      var types = this.types;
      (this.options.fields || []).forEach(function (f) {
        types[f.id] = f.type;
      });

      var filters = this._parse(this.textarea.val());
      if (filters === null || !(this.options.fields || []).length) {
        return; // keep the textarea
      }
      this.textarea.addClass("d-none");
      this.el.find("[data-filter-add]").removeClass("d-none").on("click", this._onAdd);
      var self = this;
      filters.forEach(function (f) {
        self._addRow(f);
      });
    },

    _parse: function (text) {
      if (!$.trim(text || "")) {
        return [];
      }
      try {
        var value = JSON.parse(text);
        return $.isArray(value) &&
          value.every(function (f) {
            return f && typeof f === "object" && !$.isArray(f);
          })
          ? value
          : null;
      } catch (e) {
        return null;
      }
    },

    _operator: function (op) {
      return (this.options.operators || []).filter(function (o) {
        return o.op === op;
      })[0];
    },

    _onAdd: function () {
      this._addRow({}).find("select").first().trigger("focus");
    },

    _addRow: function (filter) {
      var self = this;
      var row = $('<div class="spatialdata-filter-row d-flex flex-wrap gap-2 mb-2"></div>');
      var field = $('<select class="form-select form-control" data-filter-field></select>')
        .attr("aria-label", this._("Field"));
      field.append($("<option></option>").attr("value", "").text(this._("Field…")));
      (this.options.fields || []).forEach(function (f) {
        field.append($("<option></option>").attr("value", f.id).text(f.id));
      });
      // a saved field that's no longer in the table stays visible
      if (filter.field && !(filter.field in this.types)) {
        field.append($("<option></option>").attr("value", filter.field).text(filter.field));
      }
      field.val(filter.field || "");

      var op = $('<select class="form-select form-control" data-filter-op></select>')
        .attr("aria-label", this._("Condition"));
      var value = $('<input type="text" class="form-control" data-filter-value>')
        .attr("aria-label", this._("Value"));
      var remove = $('<button type="button" class="btn btn-sm btn-link text-danger"></button>')
        .attr("aria-label", this._("Remove filter"))
        .attr("title", this._("Remove filter"))
        .html('<i class="fa fa-times" aria-hidden="true"></i>');

      row.append(field, op, value, remove);
      this.rows.append(row);

      this._fillOperators(row, filter.op || "=");
      var v = filter.value;
      value.val($.isArray(v) ? v.join(", ") : v === undefined || v === null ? "" : String(v));
      this._updateValue(row);

      field.on("change", function () {
        self._fillOperators(row, op.val());
        self._updateValue(row);
        self._write();
      });
      op.on("change", function () {
        self._updateValue(row);
        self._write();
      });
      value.on("input change", this._onChange);
      remove.on("click", function () {
        row.remove();
        self._write();
      });
      this._write();
      return row;
    },

    _onChange: function () {
      this._write();
    },

    // Only the operators that suit the field's type.
    _fillOperators: function (row, selected) {
      var type = this.types[row.find("[data-filter-field]").val()];
      var isDate = DATE_TYPES.indexOf(type) !== -1;
      var isArray = isArrayType(type);
      var op = row.find("[data-filter-op]").empty();
      var ops = (this.options.operators || []).filter(function (o) {
        if (o.value === "interval" && type && !isDate) return false;
        if (isArray && TYPED_OPS.indexOf(o.op) !== -1) return false;
        return true;
      });
      var keep = ops.some(function (o) {
        return o.op === selected;
      });
      // A saved or submitted operator that doesn't suit the field (e.g. the
      // field's type changed) stays selected, so its error makes sense,
      // rather than silently becoming another one.
      var saved = this._operator(selected);
      if (!keep && saved && row.data("filterLoaded") !== true) {
        ops.push(saved);
        keep = true;
      }
      row.data("filterLoaded", true);
      ops.forEach(function (o) {
        op.append($("<option></option>").attr("value", o.op).text(o.label));
      });
      op.val(keep ? selected : ops.length ? ops[0].op : "");
    },

    _updateValue: function (row) {
      var operator = this._operator(row.find("[data-filter-op]").val());
      var kind = operator ? operator.value : "single";
      var type = this.types[row.find("[data-filter-field]").val()];
      var value = row.find("[data-filter-value]");
      value.toggleClass("d-none", kind === "none");
      var placeholder = this._("value");
      if (kind === "interval") {
        placeholder = this._("e.g. 1 year, 30 days");
      } else if (kind === "list") {
        placeholder = this._("values, separated by commas");
      } else if (DATE_TYPES.indexOf(type) !== -1) {
        placeholder = "YYYY-MM-DD";
      }
      value.attr("placeholder", placeholder);
    },

    _write: function () {
      var self = this;
      var filters = [];
      this.rows.children().each(function () {
        var row = $(this);
        var field = row.find("[data-filter-field]").val();
        var op = row.find("[data-filter-op]").val();
        if (!field || !op) {
          return;
        }
        var operator = self._operator(op);
        var kind = operator ? operator.value : "single";
        var raw = $.trim(row.find("[data-filter-value]").val());
        var filter = { field: field, op: op };
        if (kind === "list") {
          filter.value = raw.split(",").map($.trim).filter(Boolean);
        } else if (kind !== "none") {
          filter.value = raw;
        }
        filters.push(filter);
      });
      this.textarea.val(filters.length ? JSON.stringify(filters) : "");
    },
  };
});
