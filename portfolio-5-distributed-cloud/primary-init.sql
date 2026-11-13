-- ============================================================================
-- PostgreSQL 16 Primary Initialization (Leader)
-- ApexBank Digital - Distributed Database Portfolio 5
-- ============================================================================

-- DEV-ONLY passwords. pg_hba.conf replication rule is added by
-- 00-replication-hba.sh (primary-init-replication-hba.sh), which runs first.

-- 1. Create replication user for streaming replication
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'replicator') THEN
      CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator_dev';
   END IF;
END
$$;

-- 2. Load Portfolio 1 schema (DDL creates tables with deferred constraint triggers)
\i /tmp/ddl_schema.sql

-- 3. Load Portfolio 1 seed data wrapped in a transaction with deferred constraints.
--    Deferred triggers (journal balance, has-lines) are checked at COMMIT time,
--    after all journal_entries and ledger_entries rows are inserted.
BEGIN;
SET CONSTRAINTS ALL DEFERRED;
\i /tmp/seed_data.sql
COMMIT;

-- 4. Create physical replication slots for replicas (used by pg_basebackup -S
--    and then by each standby's walreceiver via primary_slot_name)
SELECT pg_create_physical_replication_slot('replica_1_slot');
SELECT pg_create_physical_replication_slot('replica_2_slot');

-- 5. Publication for logical replication / CDC (design placeholder only).
--    It is NOT usable with wal_level = replica; a subscriber or CDC tool
--    (e.g. Debezium) would require wal_level = logical on the primary.
CREATE PUBLICATION apexbank_publication FOR TABLE accounts, transactions, ledger_entries, journal_entries;
