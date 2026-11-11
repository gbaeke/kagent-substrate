-- Runs once, when the data directory is first initialised (docker-entrypoint-initdb.d).
-- kagent checks for pgvector in the schema named by config.database.vectorSchema ("extensions").
CREATE SCHEMA IF NOT EXISTS extensions;
GRANT USAGE ON SCHEMA extensions TO PUBLIC;
CREATE EXTENSION IF NOT EXISTS vector SCHEMA extensions;
