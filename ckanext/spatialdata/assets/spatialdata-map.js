/* Map of a georeferenced resource, drawn from the Martin vector tiles.
 *
 * Usage:
 *   <div data-module="spatialdata-map"
 *        data-module-tilejson="https://tiles.example.org/table.<id>._geom"
 *        data-module-source-layer="table.<id>._geom"
 *        data-module-basemap="https://tiles.openfreemap.org/styles/positron"
 *        data-module-bounds="[xmin, ymin, xmax, ymax]"
 *        data-module-minzoom="9"></div>
 *
 * Polygons, lines and points get their own layer, so any geometry type
 * (including mixed collections) renders. Clicking a feature shows its
 * attributes in a popup.
 */
ckan.module("spatialdata-map", function ($) {
  // Columns that are internal to the datastore/georeferencing and mean
  // nothing to someone looking at the map.
  var HIDDEN_PROPERTIES = ["_full_text", "spatialdata_wkb"];

  var SOURCE_ID = "spatialdata";
  var FILL_LAYER = "spatialdata-fill";
  var LINE_LAYER = "spatialdata-line";
  var POINT_LAYER = "spatialdata-point";

  function geometryTypeIs(types) {
    return ["match", ["geometry-type"], types, true, false];
  }

  return {
    options: {
      tilejson: null,
      sourceLayer: null,
      basemap: null,
      bounds: null,
      minzoom: 0,
      color: "#1f6feb",
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
      var color = this.options.color;
      var sourceLayer = this.options.sourceLayer;

      map.addSource(SOURCE_ID, {
        type: "vector",
        url: this.options.tilejson,
        minzoom: Number(this.options.minzoom) || 0,
      });

      map.addLayer({
        id: FILL_LAYER,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": sourceLayer,
        filter: geometryTypeIs(["Polygon", "MultiPolygon"]),
        paint: { "fill-color": color, "fill-opacity": 0.3 },
      });
      map.addLayer({
        id: LINE_LAYER,
        type: "line",
        source: SOURCE_ID,
        "source-layer": sourceLayer,
        filter: geometryTypeIs([
          "LineString", "MultiLineString", "Polygon", "MultiPolygon",
        ]),
        paint: {
          "line-color": color,
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1, 16, 2.5],
        },
      });
      map.addLayer({
        id: POINT_LAYER,
        type: "circle",
        source: SOURCE_ID,
        "source-layer": sourceLayer,
        filter: geometryTypeIs(["Point", "MultiPoint"]),
        paint: {
          "circle-color": color,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 3, 16, 6],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1,
        },
      });

      var layers = [POINT_LAYER, LINE_LAYER, FILL_LAYER];
      map.on("click", this._onClick);
      layers.forEach(function (layer) {
        map.on("mouseenter", layer, function () {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, function () {
          map.getCanvas().style.cursor = "";
        });
      });

      this._onZoom();
    },

    _onClick: function (e) {
      // Query all three layers at once so points sitting on a polygon win.
      var features = this.map.queryRenderedFeatures(e.point, {
        layers: [POINT_LAYER, LINE_LAYER, FILL_LAYER],
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
      // Tile or TileJSON failures (e.g. tile server down, CORS) are logged
      // rather than shown, since one bad tile shouldn't blank the map.
      if (window.console) {
        console.warn("spatialdata-map:", e && e.error ? e.error : e);
      }
    },

    _showMessage: function (message) {
      this.el.find(".spatialdata-map-canvas").addClass("d-none");
      this.el.find(".spatialdata-map-message").removeClass("d-none").text(message);
    },
  };
});
