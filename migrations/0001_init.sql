-- 0001_init: chunk 0 only needs proof that migrations run, in order, exactly once.
--
-- relay_meta is ops metadata (not product data): a single-row place to record
-- facts about this database that are not derivable from the schema itself.

CREATE TABLE relay_meta (
    key        text PRIMARY KEY,
    value      text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO relay_meta (key, value) VALUES ('schema_owner', 'chunk-0');
