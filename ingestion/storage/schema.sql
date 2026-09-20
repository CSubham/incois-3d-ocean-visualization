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
    -- The extent of what was stored, so downstream can find versions
    -- covering a region and period without opening any arrays.
    time_start       timestamptz,
    time_end         timestamptz,
    depth_min        double precision,
    depth_max        double precision,
    footprint        geography(Polygon, 4326),
    created_at       timestamptz NOT NULL DEFAULT now()
);

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
    depth_min        double precision,
    depth_max        double precision,
    measurements     integer NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS observation_profile_import
    ON observation_profile (import_id);
CREATE INDEX IF NOT EXISTS observation_profile_position
    ON observation_profile USING gist (position);
CREATE INDEX IF NOT EXISTS observation_profile_time
    ON observation_profile (observed_at);
CREATE INDEX IF NOT EXISTS observation_profile_platform
    ON observation_profile (platform_id);
