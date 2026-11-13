# Portfolio 5: Replication Setup & Failover Procedures
## ApexBank Digital Distributed Database

---

### 1. Starting the Topology

From the repository root:

```bash
docker compose -f portfolio-5-distributed-cloud/docker-compose.distributed.yml up -d
```

This creates:
- `mit8103-pg-primary` (postgres:16, port 5435) — leader, accepts writes
- `mit8103-pg-replica-1` (postgres:16, port 5436) — hot standby
- `mit8103-pg-replica-2` (postgres:16, port 5437) — hot standby
- `mit8103-pgbouncer` (pgbouncer:1.22, port 6432) — connection pooler

> To rebuild from scratch (e.g. after config changes), remove the volumes:
> `docker compose -f portfolio-5-distributed-cloud/docker-compose.distributed.yml down -v`, then `up -d` again.
> Replicas only bootstrap when their data volume is empty.

Wait for all containers to be healthy:

```bash
docker compose -f portfolio-5-distributed-cloud/docker-compose.distributed.yml ps
```

---

### 2. Replica Initialization (Streaming Replication)

The primary container (started with `config_file=/etc/postgresql/postgresql.conf` = `primary-postgres.conf`) runs its init scripts once, on first start:
1. `00-replication-hba.sh` (`primary-init-replication-hba.sh`) appends `host replication replicator all scram-sha-256` to `pg_hba.conf`. The image's default only allows replication from localhost.
2. `01-primary-init.sql` creates the `replicator` role, loads the Portfolio 1 schema (`ddl_schema.sql`) and seed data (`seed_data.sql`), creates two physical replication slots (`replica_1_slot`, `replica_2_slot`), and creates a logical publication `apexbank_publication`. The publication is a placeholder only: it needs `wal_level = logical` before any subscriber can use it.

The replica containers are **not** initdb'd. Their compose `command` runs this automatically when the data volume is empty:

```bash
# (inside replica N, as postgres; PGPASSWORD=replicator_dev)
until pg_basebackup -d "host=postgres-primary port=5432 user=replicator application_name=replica_N" \
      -D /var/lib/postgresql/data -X stream -R -S replica_N_slot; do sleep 3; done
exec postgres -c config_file=/etc/postgresql/postgresql.conf   # replica-postgres.conf
```

- `pg_basebackup` copies the primary's data directory. `-X stream` includes the WAL needed to make the copy consistent, and `-S` uses the pre-created slot.
- `-R` writes `standby.signal` and appends to `postgresql.auto.conf`:

```ini
primary_conninfo = 'user=replicator password=replicator_dev host=postgres-primary port=5432 application_name=replica_N ...'
primary_slot_name = 'replica_N_slot'
```

- On start, the node enters recovery as a hot standby, connects its walreceiver to the primary, and streams WAL. The loop retries while the primary is still running its init scripts or the slot does not exist yet.

Replication is **asynchronous** (`synchronous_standby_names = ''`). `pg_stat_replication.sync_state` shows `async`.

Verify replication on the primary:

```sql
-- On primary
SELECT slot_name, slot_type, active, restart_lsn
FROM pg_replication_slots;

SELECT application_name, state, sync_state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
       write_lag, flush_lag, replay_lag
FROM pg_stat_replication;
```

On each replica, confirm it is in recovery (read-only):

```sql
-- On replica
SELECT pg_is_in_recovery();  -- should return true
SELECT pg_last_wal_replay_lsn();
SELECT status, sender_host, slot_name FROM pg_stat_wal_receiver;
```

---

### 3. Failover Procedure (Primary Crash)

> Manual procedure. Do not run it against the shared lab cluster unless you plan to rebuild it with `down -v` / `up -d` afterwards.

If the primary becomes unreachable:

#### 3.1 Detect Failure
```bash
# From any client
pg_isready -h mit8103-pg-primary -p 5432  # fails
```

#### 3.2 Fence the Old Primary (prevent split-brain)
If the primary is only partitioned, not dead, it keeps accepting writes. Promoting a replica would then create **two primaries** with diverging ledgers (split-brain). Before promoting, make sure the old primary cannot accept writes, e.g. `docker stop mit8103-pg-primary` or detach it from the network. In production this is STONITH, or a Patroni leader lease held in etcd.

#### 3.3 Select Promotion Candidate
Compare WAL replay position on each replica to find the most up-to-date:

```sql
-- On each replica
SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();
```

Pick the replica with the highest LSN. Because replication is asynchronous, transactions the old primary committed but had not yet streamed are **lost** (RPO > 0). Synchronous replication (`synchronous_standby_names = 'ANY 1 (replica_1, replica_2)'`) would make RPO = 0 for acknowledged commits.

#### 3.4 Promote the Replica
```sql
-- On the chosen replica (as superuser)
SELECT pg_promote();
```

Or via `pg_ctl`:
```bash
docker exec -u postgres mit8103-pg-replica-1 pg_ctl -D /var/lib/postgresql/data promote
```

After promotion:
- `pg_is_in_recovery()` returns `false`
- The replica becomes the new primary (accepts writes)
- It no longer streams WAL from the old primary
- It starts a new **timeline** (1 → 2). A `00000002.history` file records the switch point, and the old primary's timeline-1 WAL after that point is now a divergent history
- It has no slots for the other nodes yet: create them with `SELECT pg_create_physical_replication_slot('replica_1_slot');`

#### 3.5 Reconfigure Application / pgBouncer
pgBouncer does not detect failover. Edit `pgbouncer.ini` so the `apexbank` entry points at the new primary host, then reload the running process:

```bash
docker kill -s HUP mit8103-pgbouncer          # SIGHUP = reload config
# or, on the admin console: psql -h localhost -p 6432 -U apexbank pgbouncer -c "RELOAD;"
```

(`pgbouncer -R` is an *online restart* that hands sockets to a new process. It is not a reload and is deprecated.)

#### 3.6 Reconfigure Remaining Replica
The surviving replica does **not** need a new base backup if it has not replayed past the promotion point:
- `ALTER SYSTEM SET primary_conninfo = 'host=mit8103-pg-replica-2 port=5432 user=replicator password=replicator_dev application_name=replica_1';`
- Make sure its slot exists on the new primary, then `SELECT pg_reload_conf();` (PG 13+ applies `primary_conninfo` on reload)
- With `recovery_target_timeline = 'latest'` (the default) it follows timeline 2 automatically

#### 3.7 Re-add Old Primary as Replica
Once the old primary is back, it must not restart as a primary. Its WAL may contain commits that never reached the new primary, so it has diverged:
1. Stop it cleanly, then rewind it to the new timeline:
   `pg_rewind --target-pgdata=/var/lib/postgresql/data --source-server="host=mit8103-pg-replica-2 user=apexbank dbname=apexbank" -R`
   (`wal_log_hints = on` in `primary-postgres.conf` makes this possible)
2. If `pg_rewind` fails, wipe its data directory and `pg_basebackup -R` from the new primary
3. Start it as a standby (`standby.signal` present) streaming from the new primary. The divergent, un-replicated transactions are discarded and must be reconciled from application/audit logs

---

### 4. Read/Write Split via pgBouncer

pgBouncer routes connections to configured databases:

| Database | Routes To | Use Case |
| :--- | :--- | :--- |
| `apexbank` | Primary (`mit8103-pg-primary:5432`) | Writes, balance-before-debit reads (strong consistency) |
| `apexbank_replica_1` | Replica 1 (`mit8103-pg-replica-1:5432`) | Read-only queries (eventual consistency OK) |
| `apexbank_replica_2` | Replica 2 (`mit8103-pg-replica-2:5432`) | Read-only queries, analytics |

Application logic directs writes to `apexbank` and reads to `apexbank_replica_*` based on consistency requirements. pgBouncer does not parse SQL, so it cannot split reads from writes itself.

Configuration notes:
- `auth_type = scram-sha-256`. `userlist.txt` holds a **dev-only plaintext** password, which pgBouncer needs in order to log in to PostgreSQL with SCRAM. In production, use SCRAM secrets or `auth_query`, plus TLS.
- `pool_mode = transaction`: a server connection is reassigned after each transaction, so session state (`SET`, advisory locks, `LISTEN`, temp tables) cannot be relied on. Protocol-level prepared statements work only because `max_prepared_statements = 100` (pgBouncer ≥ 1.21). The runner also disables psycopg auto-prepare through the pooler.
- `admin_users = apexbank` enables the `pgbouncer` admin console (`SHOW POOLS`, `RELOAD`).

---

### 5. Monitoring Queries

**Replication lag (on primary):**
```sql
-- WAL retained by each slot (disk-usage risk if a replica is down)
SELECT slot_name, active,
       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
FROM pg_replication_slots;

-- Lag at each stage: sent -> written -> flushed -> replayed on the standby
SELECT application_name, state, sync_state,
       pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)   AS send_lag_bytes,
       pg_wal_lsn_diff(pg_current_wal_lsn(), flush_lsn)  AS flush_lag_bytes,
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes,
       write_lag, flush_lag, replay_lag
FROM pg_stat_replication;
```

**Node role check:**
```sql
SELECT pg_is_in_recovery() AS is_replica;
-- false = primary, true = replica
```

**Connection pool status (pgBouncer admin console, `psql -h localhost -p 6432 -U apexbank pgbouncer`):**
```sql
SHOW POOLS;
SHOW STATS;
```
