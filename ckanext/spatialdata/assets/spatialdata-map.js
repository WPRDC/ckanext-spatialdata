/* Map of a georeferenced resource, drawn from the Martin vector tiles.
 *
 * Usage:
 *   <div data-module="spatialdata-map"
 *        data-module-tilejson="https://tiles.example.org/table.<id>._geom"
 *        data-module-source-layer="table.<id>._geom"
 *        data-module-basemap="https://tiles.openfreemap.org/styles/positron"
 *        data-module-bounds="[xmin, ymin, xmax, ymax]"
 *        data-module-minzoom="9"
 *        data-module-layers="[{&quot;type&quot;: &quot;fill&quot;, ...}]"
 *        data-module-style-error=""></div>
 *
 * `layers` are MapLibre layers without id/source/source-layer (see
 * lib/map_style.py); this module fills those in. Clicking a feature shows its
 * attributes in a popup.
 */
ckan.module("spatialdata-map", function ($) {
  // Columns that are internal to the datastore/georeferencing and mean
  // nothing to someone looking at the map.
  var HIDDEN_PROPERTIES = ["_full_text", "spatialdata_wkb"];

  var SOURCE_ID = "spatialdata";
  var LAYER_PREFIX = "spatialdata-layer-";

  return {
    options: {
      tilejson: null,
      sourceLayer: null,
      basemap: null,
      bounds: null,
      minzoom: 0,
      layers: [],
      styleError: "",
    },

    initialize: function () {
      $.proxyAll(this, /_on/);

      if (typeof maplibregl === "undefined") {
        this._showMessage(this._("The map library failed to load."));
        return;
      }
      var mapOptions = {
        container: this.el.find(".spatialdata-map-canvas").get(0),
        style: this.options.basemap,
        attributionControl: { compact: true },
        cooperativeGestures: false,
      };
      var bounds = this.options.bounds;
      if (bounds && bounds.length === 4) {
        mapOptions.bounds = bounds;
        mapOptions.fitBoundsOptions = { padding: 24, maxZoom: 16 };
      } else {
        mapOptions.center = [0, 0];
        mapOptions.zoom = 1;
      }

      try {
        this.map = new maplibregl.Map(mapOptions);
      } catch (e) {
        this._showMessage(this._("Your browser could not display the map (WebGL is required)."));
        return;
      }

      this.map.addControl(new maplibregl.NavigationControl(), "top-right");
      this.map.addControl(new maplibregl.FullscreenControl(), "top-right");
      this.map.addControl(new maplibregl.ScaleControl(), "bottom-left");

      this.zoomHint = this.el.find(".spatialdata-map-zoom-hint");
      this.layerIds = [];
      if (this.options.styleError) {
        this._showStyleError(this.options.styleError);
      }
      this.map.on("load", this._onLoad);
      this.map.on("zoomend", this._onZoom);
      this.map.on("error", this._onError);
    },

    teardown: function () {
      if (this.map) {
        this.map.remove();
      }
    },

    _onLoad: function () {
      var map = this.map;
      var sourceLayer = this.options.sourceLayer;
      var layerIds = this.layerIds;

      map.addSource(SOURCE_ID, {
        type: "vector",
        url: this.options.tilejson,
        minzoom: Number(this.options.minzoom) || 0,
      });

      (this.options.layers || []).forEach(function (layer, i) {
        var id = LAYER_PREFIX + i;
        // Invalid paint/layout values are reported through the map's
        // "error" event (see _onError), not thrown.
        map.addLayer($.extend({}, layer, {
          id: id,
          source: SOURCE_ID,
          "source-layer": sourceLayer,
        }));
        if (map.getLayer(id)) {
          layerIds.push(id);
        }
      });

      map.on("click", this._onClick);
      layerIds.forEach(function (id) {
        map.on("mouseenter", id, function () {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", id, function () {
          map.getCanvas().style.cursor = "";
        });
      });

      this._onZoom();
    },

    _onClick: function (e) {
      if (!this.layerIds.length) {
        return;
      }
      // Features come back topmost first.
      var features = this.map.queryRenderedFeatures(e.point, {
        layers: this.layerIds,
      });
      if (!features.length) {
        return;
      }
      new maplibregl.Popup({ maxWidth: "360px" })
        .setLngLat(e.lngLat)
        .setDOMContent(this._popupContent(features[0].properties))
        .addTo(this.map);
    },

    _popupContent: function (properties) {
      // Build with DOM nodes and textContent: property values are user data.
      var wrapper = document.createElement("div");
      wrapper.className = "spatialdata-map-popup";
      var table = document.createElement("table");
      table.className = "table table-sm mb-0";
      var rows = 0;
      Object.keys(properties).forEach(function (key) {
        if (HIDDEN_PROPERTIES.indexOf(key) !== -1) {
          return;
        }
        var tr = document.createElement("tr");
        var th = document.createElement("th");
        var td = document.createElement("td");
        th.textContent = key;
        td.textContent = properties[key];
        tr.appendChild(th);
        tr.appendChild(td);
        table.appendChild(tr);
        rows += 1;
      });
      if (rows) {
        wrapper.appendChild(table);
      } else {
        wrapper.textContent = this._("No attributes");
      }
      return wrapper;
    },

    _onZoom: function () {
      var minzoom = Number(this.options.minzoom) || 0;
      this.zoomHint.toggleClass("d-none", this.map.getZoom() >= minzoom);
    },

    _onError: function (e) {
      var error = e && e.error ? e.error : e;
      // Style problems in the view's layers are shown, so whoever wrote the
      // style can see them in the preview. Tile or TileJSON failures (e.g.
      // tile server down, CORS) are only logged, since one bad tile
      // shouldn't cover the map.
      var message = error && error.message ? error.message : String(error);
      if (message.indexOf(LAYER_PREFIX) !== -1) {
        // number layers from 1, like the server-side validation messages
        var layerLabel = this._("layer");
        this._showStyleError(message.replace(/(?:layers\.)?spatialdata-layer-(\d+)/g, function (m, n) {
          return layerLabel + " " + (Number(n) + 1);
        }));
      }
      if (window.console) {
        console.warn("spatialdata-map:", error);
      }
    },

    _showStyleError: function (message) {
      var el = this.el.find(".spatialdata-map-message");
      var text = this._("Style error: ") + message;
      el.text(el.text() ? el.text() + "\n" + text : text).removeClass("d-none");
    },

    _showMessage: function (message) {
      this.el.find(".spatialdata-map-canvas").addClass("d-none");
      this.el.find(".spatialdata-map-message").removeClass("d-none").text(message);
    },
  };
});
