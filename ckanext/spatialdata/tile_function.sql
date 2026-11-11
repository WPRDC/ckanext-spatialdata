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
-- filters:  optional JSON list of {"field", "op", "value"}; only rows matching
--           all of them are drawn (see lib/filters.py). No text from a filter
--           goes into the SQL: fields must be columns of the table and are
--           quoted, operators come from a fixed list, and values are passed as
--           a query parameter ($4) and cast to the column's type. A filter
--           that breaks these rules raises an error, so the tile fails rather
--           than showing unfiltered rows.
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
    filters   jsonb := coalesce(query_params ->> 'filters', '[]')::jsonb;
    conds     text := '';
    flt       jsonb;
    flt_field text;
    flt_op    text;
    col_type  text;
    col_array boolean;
    val_sql   text;  -- SQL that reads the filter's value from $4
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

    -- Filters. Limits and operators match lib/filters.py.
    IF jsonb_typeof(filters) <> 'array' OR jsonb_array_length(filters) > 10 THEN
        RAISE EXCEPTION 'spatialdata_tiles: filters must be a list of at most 10 filters';
    END IF;

    FOR k IN 0 .. jsonb_array_length(filters) - 1 LOOP
        flt := filters -> k;
        flt_field := flt ->> 'field';
        flt_op := flt ->> 'op';

        IF flt_op IS NULL OR flt_op NOT IN (
            '=', '!=', '<', '<=', '>', '>=', 'in', 'not in',
            'contains', 'empty', 'not empty', 'last'
        ) THEN
            RAISE EXCEPTION 'spatialdata_tiles: filter % has an unknown operator', k + 1;
        END IF;

        -- the column's type, from the catalog; NULL if it isn't a column
        col_type := NULL;
        SELECT format_type(a.atttypid, a.atttypmod), t.typcategory = 'A'
        INTO col_type, col_array
        FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
        WHERE a.attrelid = format('public.%I', tbl)::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND a.attname = flt_field
          AND a.attname NOT IN ('_full_text', '{geom_field}', '{mercator_field}', 'spatialdata_wkb');
        IF col_type IS NULL THEN
            RAISE EXCEPTION 'spatialdata_tiles: filter % is on an unknown field', k + 1;
        END IF;

        IF col_array AND flt_op NOT IN ('contains', 'empty', 'not empty') THEN
            RAISE EXCEPTION 'spatialdata_tiles: filter % compares a list field', k + 1;
        END IF;
        IF flt_op IN ('in', 'not in') AND (
            jsonb_typeof(flt -> 'value') IS DISTINCT FROM 'array'
            OR jsonb_array_length(flt -> 'value') > 100
        ) THEN
            RAISE EXCEPTION 'spatialdata_tiles: filter % needs a list of at most 100 values', k + 1;
        END IF;
        IF flt_op = 'last' AND (
            col_type NOT IN ('date', 'timestamp without time zone', 'timestamp with time zone')
            OR coalesce(flt ->> 'value', '') !~ '^\d{1,4} (minute|hour|day|week|month|year)s?$'
        ) THEN
            RAISE EXCEPTION 'spatialdata_tiles: filter % needs a date field and a value like "1 year"', k + 1;
        END IF;

        -- k is an integer and col_type comes from the catalog
        val_sql := format('($4 -> %s ->> ''value'')::%s', k, col_type);

        conds := conds || ' AND ' || CASE flt_op
            WHEN '='  THEN format('%I = %s', flt_field, val_sql)
            WHEN '!=' THEN format('%I IS DISTINCT FROM %s', flt_field, val_sql)
            WHEN '<'  THEN format('%I < %s', flt_field, val_sql)
            WHEN '<=' THEN format('%I <= %s', flt_field, val_sql)
            WHEN '>'  THEN format('%I > %s', flt_field, val_sql)
            WHEN '>=' THEN format('%I >= %s', flt_field, val_sql)
            WHEN 'in' THEN format(
                '%I = ANY (ARRAY(SELECT jsonb_array_elements_text($4 -> %s -> ''value''))::%s[])',
                flt_field, k, col_type)
            -- rows with no value aren't "one of" the values, so they're kept
            WHEN 'not in' THEN format(
                'NOT coalesce(%I = ANY (ARRAY(SELECT jsonb_array_elements_text($4 -> %s -> ''value''))::%s[]), false)',
                flt_field, k, col_type)
            WHEN 'contains' THEN format(
                'strpos(lower(%I::text), lower($4 -> %s ->> ''value'')) > 0', flt_field, k)
            WHEN 'empty' THEN format('(%I IS NULL OR %I::text = '''')', flt_field, flt_field)
            WHEN 'not empty' THEN format('(%I IS NOT NULL AND %I::text <> '''')', flt_field, flt_field)
            WHEN 'last' THEN format(
                '%I >= now() - ($4 -> %s ->> ''value'')::interval', flt_field, k)
        END;
    END LOOP;

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
                %s
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
        tbl,
        conds
    ) INTO tile USING z, x, y, filters;

    RETURN tile;
END;
$body$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

COMMENT ON FUNCTION public.spatialdata_tiles(integer, integer, integer, json) IS
    'ckanext-spatialdata map view tiles: ?resource=<resource id>&fields=a,b&filters=<json>';
