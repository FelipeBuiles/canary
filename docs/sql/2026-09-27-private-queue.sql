-- Run once as the Supabase postgres administrator, before queue bootstrap.
-- Deliberately fails if the role/schema already exists; never rotate credentials
-- or take ownership of an existing queue implicitly.
BEGIN;

CREATE ROLE canary_queue NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 10;
GRANT canary_queue TO postgres;
CREATE SCHEMA canary_queue AUTHORIZATION canary_queue;
REVOKE ALL ON SCHEMA canary_queue FROM PUBLIC, anon, authenticated, service_role;
GRANT CONNECT ON DATABASE postgres TO canary_queue;

-- Both bootstrap and workers use this path with the queue role. No public
-- fallback: an absent private schema must fail instead of creating public tables.
ALTER ROLE canary_queue IN DATABASE postgres SET search_path = canary_queue;

-- Function EXECUTE and type USAGE are granted to PUBLIC by PostgreSQL by
-- default. Revoke those global defaults for objects created by this role.
ALTER DEFAULT PRIVILEGES FOR ROLE canary_queue REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE canary_queue REVOKE USAGE ON TYPES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE canary_queue IN SCHEMA canary_queue
    REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE canary_queue IN SCHEMA canary_queue
    REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated, service_role;

COMMIT;

-- Provisioning sets a generated password and LOGIN separately through the
-- administrator connection. Never commit that password or expose this schema
-- through Supabase's Data API. Bootstrap using the queue role, not postgres.
