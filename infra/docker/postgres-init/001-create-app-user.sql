-- Runtime identities are deliberately separate from the migration owner.
-- glint_app remains only as a NOLOGIN compatibility role for old migrations;
-- the final role-policy migration revokes every object privilege from it.
CREATE ROLE glint_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
CREATE ROLE glint_api LOGIN PASSWORD 'glint_api_dev_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
CREATE ROLE glint_worker LOGIN PASSWORD 'glint_worker_dev_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE glint TO glint_api, glint_worker;
GRANT USAGE ON SCHEMA public TO glint_api, glint_worker;

-- No default table or sequence privileges are granted to either runtime.
-- Alembic owns every explicit grant so a newly added table fails closed.
