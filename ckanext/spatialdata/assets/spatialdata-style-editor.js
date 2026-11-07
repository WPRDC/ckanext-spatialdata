/* JSON editor for the map view's style, built on CodeMirror 5.
 *
 * Usage:
 *   <div data-module="spatialdata-style-editor">
 *     <textarea name="style">...</textarea>
 *     <textarea hidden data-style-default>...default style JSON...</textarea>
 *     <button type="button" data-style-reset>Reset to default</button>
 *     <div data-style-status></div>
 *     <ul data-style-problems></ul>
 *   </div>
 *
 * The textarea stays the form field; CodeMirror writes back to it on every
 * change. Every change is checked with MapLibre's style validator
 * (maplibre-gl-style-spec), and the form's save button is disabled while
 * there are problems. Preview still works, so problems can be seen on the
 * map.
 */
ckan.module("spatialdata-style-editor", function ($) {
  // Must match ALLOWED_LAYER_TYPES in lib/map_style.py.
  var ALLOWED_LAYER_TYPES = ["fill", "line", "circle", "symbol", "heatmap", "fill-extrusion"];
  var LAYER_PREFIX = "spatialdata-layer-";

  return {
    initialize: function () {
      $.proxyAll(this, /_on/);
      var textarea = this.el.find("textarea[name=style]").get(0);
      this.defaultStyle = this.el.find("[data-style-default]").val();
      this.status = this.el.find("[data-style-status]");
      this.problemList = this.el.find("[data-style-problems]");
      this.problems = [];

      if (typeof CodeMirror === "undefined") {
        // the plain textarea still works; the server checks it on save
        return;
      }

      this.editor = CodeMirror.fromTextArea(textarea, {
        mode: { name: "javascript", json: true },
        lineNumbers: true,
        matchBrackets: true,
        autoCloseBrackets: true,
        tabSize: 2,
        indentUnit: 2,
        indentWithTabs: false,
        viewportMargin: Infinity,
        extraKeys: {
          // keep Tab for indenting; Esc then Tab still leaves the editor
          Tab: function (cm) {
            cm.execCommand(cm.somethingSelected() ? "indentMore" : "insertSoftTab");
          },
          "Shift-Tab": "indentLess",
        },
      });
      this.editor.on("change", this._onChange);
      this.el.find("[data-style-reset]").on("click", this._onReset);
      this.saveButton = $(textarea.form).find("button[name=save]");
      $(textarea.form).on("submit", this._onSubmit);
      this._onChange();
    },

    _onReset: function () {
      this.editor.setValue(this.defaultStyle);
      this.editor.focus();
    },

    _onSubmit: function (e) {
      var submitter = e.originalEvent && e.originalEvent.submitter;
      // Only saving is blocked: Preview shows the problems on the map, and
      // Delete doesn't care about the style.
      if (!submitter || submitter.name !== "save" || !this.problems.length) {
        return;
      }
      e.preventDefault();
      // CKAN's basic-form module disables the button on every submit, even
      // a cancelled one; leave it to _show to decide.
      var self = this;
      setTimeout(function () {
        self.saveButton.prop("disabled", self.problems.length > 0);
      }, 0);
      this.el.get(0).scrollIntoView({ block: "center" });
      this.editor.focus();
    },

    _onChange: function () {
      this.editor.save();
      var text = this.editor.getValue().trim();
      if (!text) {
        this._show([], this._("Empty: the default style is used."), "");
        return;
      }

      var layers;
      try {
        layers = JSON.parse(text);
      } catch (e) {
        this._show([e.message]);
        return;
      }

      var problems = this._validate(layers);
      if (problems.length) {
        this._show(problems);
      } else {
        this._show(
          [],
          layers.length === 1
            ? this._("Valid style: 1 layer.")
            : this._("Valid style: %(count)s layers.", { count: layers.length }),
          "text-success"
        );
      }
    },

    _validate: function (layers) {
      var _ = this._.bind(this);
      if (!Array.isArray(layers) || !layers.length) {
        return [_("The style must be a non-empty list of layers.")];
      }

      var problems = [];
      layers.forEach(function (layer, i) {
        if (!layer || typeof layer !== "object" || Array.isArray(layer)) {
          problems.push(_("Layer %(n)s must be an object.", { n: i + 1 }));
        } else if (ALLOWED_LAYER_TYPES.indexOf(layer.type) === -1) {
          problems.push(
            _('Layer %(n)s: "type" must be one of %(types)s.', {
              n: i + 1,
              types: ALLOWED_LAYER_TYPES.join(", "),
            })
          );
        }
      });
      if (problems.length || typeof maplibreGlStyleSpecification === "undefined") {
        return problems;
      }

      // Check the layers the way the map view will add them: with an id,
      // source and source-layer. The glyphs URL is only there so text
      // layers validate; the map uses the basemap's glyphs.
      var style = {
        version: 8,
        glyphs: "https://glyphs.invalid/{fontstack}/{range}.pbf",
        sources: { spatialdata: { type: "vector", url: "https://tiles.invalid/tiles.json" } },
        layers: layers.map(function (layer, i) {
          return $.extend({}, layer, {
            id: LAYER_PREFIX + i,
            source: "spatialdata",
            "source-layer": "data",
          });
        }),
      };
      return maplibreGlStyleSpecification.validateStyleMin(style).map(function (error) {
        return error.message
          // "layers[0].paint..." or "layers.spatialdata-layer-0.paint..." -> "layer 1: paint..."
          .replace(/^layers(?:\[(\d+)\]|\.spatialdata-layer-(\d+))\.?/, function (m, a, b) {
            return _("Layer %(n)s", { n: Number(a || b) + 1 }) + ": ";
          })
          .replace(new RegExp(LAYER_PREFIX + "(\\d+)", "g"), function (m, n) {
            return _("layer %(n)s", { n: Number(n) + 1 });
          });
      });
    },

    _show: function (problems, okText, okClass) {
      this.problems = problems;
      this.saveButton.prop("disabled", problems.length > 0);
      this.problemList.empty();
      this.status.removeClass("text-success text-danger");

      if (!problems.length) {
        this.status.addClass(okClass || "").text(okText || "");
        return;
      }

      this.status
        .addClass("text-danger")
        .text(
          problems.length === 1
            ? this._("1 problem. Fix it to save.")
            : this._("%(count)s problems. Fix them to save.", { count: problems.length })
        );
      var list = this.problemList;
      problems.forEach(function (problem) {
        list.append($("<li>").text(problem));
      });
    },
  };
});
