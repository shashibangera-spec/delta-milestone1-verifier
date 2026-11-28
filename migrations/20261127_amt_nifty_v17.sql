-- Isolated NIFTY 50 Spot V1.7 grants. Tables are created by amt_nifty_writer_login.
CREATE SCHEMA IF NOT EXISTS amt_nifty_v17;
GRANT USAGE ON SCHEMA amt_nifty_v17 TO amt_dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA amt_nifty_v17 TO amt_dashboard_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE amt_nifty_writer_login IN SCHEMA amt_nifty_v17
  GRANT SELECT ON TABLES TO amt_dashboard_ro;
