/* Map of a georeferenced resource, drawn from the tile server.
 *
 * Usage:
 *   <div data-module="spatialdata-map"
 *        data-module-tiles="https://tiles.example.org/public.spatialdata_tiles/{z}/{x}/{y}?resource=<id>&fields=a,b"
 *        data-module-source-layer="features"
 *        data-module-feature-url="/dataset/<pkg>/resource/<id>/spatialdata/feature/0"
 *        data-module-title-field="a"
 *        data-module-hover-fields="[&quot;b&quot;]"
 *        data-module-basemap="https://tiles.openfreemap.org/styles/positron"
 *        data-module-bounds="[xmin, ymin, xmax, ymax]"
 *        data-module-minzoom="9"
 *        data-module-layers="[{&quot;type&quot;: &quot;fill&quot;, ...}]"
 *        data-module-style-error=""></div>
 *
 * `layers` are MapLibre layers without id/source/source-layer (see
 * lib/map_style.py); this module fills those in.
 *
 * The tiles carry only `_id` and a few chosen fields (lib/tiles.py). Hovering
 * a feature shows its title field and hover fields from the tile; clicking it
 * fetches the whole row's popup from feature-url (with the trailing 0
 * replaced by the feature's `_id`).
 */
ckan.module("spatialdata-map", function ($) {
  var SOURCE_ID = "spatialdata";
  var LAYER_PREFIX = "spatialdata-layer-";

  return {
    options: {
      tiles: null,
      sourceLayer: null,
      featureUrl: null,
      titleField: null,
      hoverFields: [],
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
      if (this.popupRequest) {
        this.popupRequest.abort();
      }
      if (this.map) {
        this.map.remove();
      }
    },

    _onLoad: function () {
      var map = this.map;
      var sourceLayer = this.options.sourceLayer;
      var layerIds = this.layerIds;

      var source = {
        type: "vector",
        tiles: [this.options.tiles],
        minzoom: Number(this.options.minzoom) || 0,
        maxzoom: 18,
      };
      var bounds = this.options.bounds;
      if (bounds && bounds.length === 4) {
        // no requests for tiles outside the data
        source.bounds = bounds;
      }
      map.addSource(SOURCE_ID, source);

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

      this.hoverPopup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        maxWidth: "300px",
        offset: 8,
        className: "spatialdata-map-hover",
      });
      map.on("click", this._onClick);
      map.on("mousemove", this._onMouseMove);
      map.getCanvas().addEventListener("mouseleave", this._onMouseLeaveCanvas);

      this._onZoom();
    },

    _featureAt: function (point) {
      if (!this.layerIds.length) {
        return null;
      }
      // Features come back topmost first.
      var features = this.map.queryRenderedFeatures(point, {
        layers: this.layerIds,
      });
      return features.length ? features[0] : null;
    },

    _onMouseMove: function (e) {
      var feature = this._featureAt(e.point);
      this.map.getCanvas().style.cursor = feature ? "pointer" : "";
      var content = feature && this._hoverContent(feature.properties);
      if (!content) {
        this.hoverPopup.remove();
        return;
      }
      var id = feature.properties._id;
      if (id !== this.hoveredId || !this.hoverPopup.isOpen()) {
        this.hoveredId = id;
        this.hoverPopup.setDOMContent(content);
      }
      this.hoverPopup.setLngLat(e.lngLat).addTo(this.map);
    },

    _onMouseLeaveCanvas: function () {
      this.hoveredId = null;
      if (this.hoverPopup) {
        this.hoverPopup.remove();
      }
    },

    _hoverContent: function (properties) {
      // Built with textContent: property values are user data.
      var title = this.options.titleField
        ? properties[this.options.titleField]
        : null;
      var fields = (this.options.hoverFields || []).filter(function (key) {
        return properties[key] !== undefined && properties[key] !== null;
      });
      var hasTitle = title !== null && title !== undefined && title !== "";
      if (!hasTitle && !fields.length) {
        return null;
      }
      var wrapper = document.createElement("div");
      wrapper.className = "spatialdata-map-popup";
      if (hasTitle) {
        var heading = document.createElement("h3");
        heading.className = "spatialdata-map-popup-title";
        heading.textContent = title;
        wrapper.appendChild(heading);
      }
      if (fields.length) {
        var table = document.createElement("table");
        table.className = "table table-sm mb-0";
        fields.forEach(function (key) {
          var tr = document.createElement("tr");
          var th = document.createElement("th");
          var td = document.createElement("td");
          th.textContent = key;
          td.textContent = properties[key];
          tr.appendChild(th);
          tr.appendChild(td);
          table.appendChild(tr);
        });
        wrapper.appendChild(table);
      }
      return wrapper;
    },

    _onClick: function (e) {
      var feature = this._featureAt(e.point);
      if (!feature || feature.properties._id === undefined) {
        return;
      }
      this.hoverPopup.remove();
      if (this.popupRequest) {
        this.popupRequest.abort();
      }

      var body = document.createElement("div");
      body.className = "spatialdata-map-popup";
      body.textContent = this._("Loading…");
      var popup = new maplibregl.Popup({ maxWidth: "360px" })
        .setLngLat(e.lngLat)
        .setDOMContent(body)
        .addTo(this.map);

      var url = String(this.options.featureUrl).replace(
        /\/0$/,
        "/" + encodeURIComponent(feature.properties._id)
      );
      var module = this;
      this.popupRequest = $.ajax({ url: url, dataType: "html" })
        .done(function (html) {
          // Rendered by CKAN from the row and the resource's popup template,
          // which is sanitized Markdown (lib/popup.py).
          var content = $($.parseHTML(html)).filter(".spatialdata-map-popup");
          popup.setDOMContent(content.length ? content.get(0) : body);
        })
        .fail(function (xhr, status) {
          if (status !== "abort") {
            body.textContent = module._("Could not load this feature's details.");
          }
        })
        .always(function () {
          module.popupRequest = null;
        });
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
