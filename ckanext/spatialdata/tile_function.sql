-- Vector tiles for the map view (spatialdata_view), with only the columns it
-- needs, so tiles of large tables stay small. Martin publishes this as a
-- function source ("public.spatialdata_tiles" with martin/config.yaml's
-- '{schema}.{function}' source_id_format) and passes the tile request's query
-- string as query_params:
--
--   /public.spatialdata_tiles/{z}/{x}/{y}?resource=<resource id>&fields=a,b
--
-- resource: a georeferenced datastore table (one with a geometry column named
--           {mercator_field}); anything else gives an empty tile.
-- fields:   comma-separated columns to include besides _id. Names that aren't
--           columns of the table, and internal columns, are ignored.
--
-- The tile has one layer, "{layer}". Installed by `ckan spatialdata-init-tiles`.
--
-- Below zoom 16, points are thinned to one per 2-pixel cell (16 of the
-- tile's 4096 units; tiles are drawn 512 px wide), keeping the newest row.
-- Points that close overlap on the map anyway, and dense tables otherwise
-- give tiles of several MB at low zooms. Lines and polygons are all kept.
CREATE OR REPLACE FUNCTION public.spatialdata_tiles(
    z integer, x integer, y integer, query_params json
) RETURNS bytea
AS
$body$
DECLARE
    tbl       text := query_params ->> 'resource';
    requested text[] := string_to_array(coalesce(query_params ->> 'fields', ''), ',');
    cols      text;
    tile      bytea;
BEGIN
    IF tbl IS NULL OR NOT EXISTS (
        SELECT 1 FROM geometry_columns
        WHERE f_table_schema = 'public'
          AND f_table_name = tbl
          AND f_geometry_column = '{mercator_field}'
    ) THEN
        RETURN NULL;
    END IF;

    -- Only real columns, quoted. JSON is sent as text: ST_AsMVT would
    -- otherwise spread a jsonb object's keys out as separate properties.
    SELECT string_agg(
               CASE WHEN a.atttypid IN ('json'::regtype, 'jsonb'::regtype)
                    THEN format('%I::text AS %I', a.attname, a.attname)
                    ELSE format('%I', a.attname) END,
               ', ' ORDER BY a.attnum)
    INTO cols
    FROM pg_attribute a
    WHERE a.attrelid = format('public.%I', tbl)::regclass
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND a.attname = ANY (SELECT btrim(f) FROM unnest(requested) f)
      AND a.attname NOT IN ('_id', '_full_text', '{geom_field}', '{mercator_field}', 'spatialdata_wkb');

    EXECUTE format(
        $sql$
        SELECT ST_AsMVT(t, '{layer}', 4096, 'geom')
        FROM (
            SELECT DISTINCT ON (cell) _id%s, geom
            FROM (
                SELECT *,
                       ST_AsMVTGeom("{mercator_field}", ST_TileEnvelope($1, $2, $3), 4096, 64, true) AS geom
                FROM public.%I
                WHERE "{mercator_field}" && ST_TileEnvelope($1, $2, $3, margin => (64.0 / 4096))
            ) rows,
            LATERAL (
                SELECT CASE WHEN $1 < 16 AND GeometryType(rows.geom) = 'POINT'
                            THEN ST_AsBinary(ST_SnapToGrid(rows.geom, 16))
                            ELSE int8send(rows._id) END AS cell
            ) cells
            WHERE geom IS NOT NULL
            ORDER BY cell, _id DESC
        ) t
        $sql$,
        coalesce(', ' || cols, ''),
        tbl
    ) INTO tile USING z, x, y;

    RETURN tile;
END;
$body$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

COMMENT ON FUNCTION public.spatialdata_tiles(integer, integer, integer, json) IS
    'ckanext-spatialdata map view tiles: ?resource=<resource id>&fields=a,b';
