-- S3 catalogue.
--
-- One row per accepted import, never updated. A repeat import of the same
-- selection is a new version; nothing here is edited in place, so a
-- reference handed downstream stays valid.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS dataset_version (
    import_id        text PRIMARY KEY,
    source_id        text NOT NULL,
    source_name      text NOT NULL,
    dataset_id       text NOT NULL,
    dataset_name     text NOT NULL,
    source_kind      text NOT NULL,
    geometry         text NOT NULL,
    object_ref       text NOT NULL,
    location         text,
    sizes            jsonb NOT NULL DEFAULT '{}'::jsonb,
    selection        jsonb NOT NULL DEFAULT '{}'::jsonb,
    validation       jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata         jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_details   jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Exact model coordinate values make catalogue listing independent of
    -- object-store reads. Nullable because catalogues created before this
    -- addition retain their existing immutable rows.
    time_values      jsonb,
    depth_values     jsonb,
    -- The extent of what was stored, so downstream can find versions
    -- covering a region and period without opening any arrays.
    time_start       timestamptz,
    time_end         timestamptz,
    vertical_min     double precision,
    vertical_max     double precision,
    vertical_kind    text CHECK (vertical_kind IN ('depth', 'pressure')),
    vertical_units   text,
    -- Backward-compatible depth-only view. Pressure is never stored here.
    depth_min        double precision,
    depth_max        double precision,
    footprint        geography(Polygon, 4326),
    created_at       timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE dataset_version
    ADD COLUMN IF NOT EXISTS time_values jsonb;
ALTER TABLE dataset_version
    ADD COLUMN IF NOT EXISTS depth_values jsonb;
ALTER TABLE dataset_version
    ADD COLUMN IF NOT EXISTS vertical_min double precision;
ALTER TABLE dataset_version
    ADD COLUMN IF NOT EXISTS vertical_max double precision;
ALTER TABLE dataset_version
    ADD COLUMN IF NOT EXISTS vertical_kind text;
ALTER TABLE dataset_version
    ADD COLUMN IF NOT EXISTS vertical_units text;

-- Migrate immutable rows written before semantic vertical extents existed.
-- Their old depth columns held the generic vertical coordinate. Units were
-- already preserved in canonical metadata, so no conversion or guess is
-- needed. Unknown units remain explicit null semantics.
UPDATE dataset_version
SET vertical_units = NULLIF(BTRIM(metadata #>>
        '{coordinate_units,vertical}'), '')
WHERE vertical_units IS NULL;

UPDATE dataset_version
SET vertical_kind = CASE LOWER(BTRIM(vertical_units))
        WHEN 'dbar' THEN 'pressure'
        WHEN 'dbars' THEN 'pressure'
        WHEN 'decibar' THEN 'pressure'
        WHEN 'decibars' THEN 'pressure'
        WHEN 'db' THEN 'pressure'
        WHEN 'm' THEN 'depth'
        WHEN 'meter' THEN 'depth'
        WHEN 'meters' THEN 'depth'
        WHEN 'metre' THEN 'depth'
        WHEN 'metres' THEN 'depth'
        ELSE NULL
    END
WHERE vertical_kind IS NULL;

UPDATE dataset_version
SET vertical_min = COALESCE(vertical_min, depth_min),
    vertical_max = COALESCE(vertical_max, depth_max)
WHERE vertical_min IS NULL OR vertical_max IS NULL;

UPDATE dataset_version
SET depth_min = NULL, depth_max = NULL
WHERE vertical_kind = 'pressure'
  AND (depth_min IS NOT NULL OR depth_max IS NOT NULL);

CREATE INDEX IF NOT EXISTS dataset_version_dataset
    ON dataset_version (source_id, dataset_id);
CREATE INDEX IF NOT EXISTS dataset_version_geometry
    ON dataset_version (geometry);
CREATE INDEX IF NOT EXISTS dataset_version_time
    ON dataset_version (time_start, time_end);
CREATE INDEX IF NOT EXISTS dataset_version_footprint
    ON dataset_version USING gist (footprint);

-- What each version contains, so a variable can be found without opening
-- the array it lives in.
CREATE TABLE IF NOT EXISTS dataset_variable (
    import_id        text NOT NULL
                     REFERENCES dataset_version (import_id) ON DELETE CASCADE,
    name             text NOT NULL,
    original_name    text,
    units            text,
    standard_name    text,
    long_name        text,
    dimensions       text[] NOT NULL DEFAULT '{}',
    fill_value       double precision,
    PRIMARY KEY (import_id, name)
);

CREATE INDEX IF NOT EXISTS dataset_variable_standard_name
    ON dataset_variable (standard_name);

-- Observation profiles, for spatial lookup of instruments. Only populated
-- for datasets whose shape is a profile, trajectory or point -- a gridded
-- field has no instrument to find.
CREATE TABLE IF NOT EXISTS observation_profile (
    id               bigserial PRIMARY KEY,
    import_id        text NOT NULL
                     REFERENCES dataset_version (import_id) ON DELETE CASCADE,
    platform_id      text,
    cycle            text,
    observed_at      timestamptz,
    position         geography(Point, 4326) NOT NULL,
    -- Source row selected under the first-complete-row marker policy.
    -- Nullable only for rows written before the policy was persisted.
    representative_source_index integer
                     CHECK (representative_source_index >= 0),
    vertical_min     double precision,
    vertical_max     double precision,
    vertical_kind    text CHECK (vertical_kind IN ('depth', 'pressure')),
    vertical_units   text,
    -- Backward-compatible depth-only view. Pressure is never stored here.
    depth_min        double precision,
    depth_max        double precision,
    measurements     integer NOT NULL DEFAULT 0
);

ALTER TABLE observation_profile
    ADD COLUMN IF NOT EXISTS representative_source_index integer;
ALTER TABLE observation_profile
    ADD COLUMN IF NOT EXISTS vertical_min double precision;
ALTER TABLE observation_profile
    ADD COLUMN IF NOT EXISTS vertical_max double precision;
ALTER TABLE observation_profile
    ADD COLUMN IF NOT EXISTS vertical_kind text;
ALTER TABLE observation_profile
    ADD COLUMN IF NOT EXISTS vertical_units text;

UPDATE observation_profile AS profile
SET vertical_min = COALESCE(profile.vertical_min, profile.depth_min),
    vertical_max = COALESCE(profile.vertical_max, profile.depth_max),
    vertical_kind = COALESCE(profile.vertical_kind, version.vertical_kind),
    vertical_units = COALESCE(profile.vertical_units, version.vertical_units)
FROM dataset_version AS version
WHERE profile.import_id = version.import_id
  AND (profile.vertical_min IS NULL OR profile.vertical_max IS NULL
       OR profile.vertical_kind IS NULL OR profile.vertical_units IS NULL);

UPDATE observation_profile
SET depth_min = NULL, depth_max = NULL
WHERE vertical_kind = 'pressure'
  AND (depth_min IS NOT NULL OR depth_max IS NOT NULL);

CREATE INDEX IF NOT EXISTS observation_profile_import
    ON observation_profile (import_id);
CREATE INDEX IF NOT EXISTS observation_profile_position
    ON observation_profile USING gist (position);
CREATE INDEX IF NOT EXISTS observation_profile_time
    ON observation_profile (observed_at);
CREATE INDEX IF NOT EXISTS observation_profile_platform
    ON observation_profile (platform_id);
