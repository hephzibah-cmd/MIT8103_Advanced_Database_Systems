# Portfolio 5: Distributed and Cloud Database Exercise
## Case Study: ApexBank Digital (Next-Generation Digital Banking & Fintech Platform)

**Course:** MIT 8103 Advanced Database Systems  
**Database Engine:** PostgreSQL 16 (Primary + Read Replicas)  
**Marks Allocated:** 6 Marks  
**Case Study:** ApexBank Digital (same as Portfolios 1–4)

---

### 1. Executive Summary

Portfolio 5 extends the ApexBank Digital case study into **distributed and cloud database architecture**. Building on the Portfolio 1 relational schema (PostgreSQL 16), this portfolio designs and implements a multi-node deployment featuring:

- **Streaming replication** — one primary (leader) accepting writes, two hot-standby read replicas receiving WAL
- **Read/write splitting** — writes directed to primary, reads distributed across replicas
- **Connection pooling** — pgBouncer transaction pooler with one pool per node (application chooses the pool)
- **Sharding design** — hash partitioning on account_id for horizontal write scale (design + routing simulation; not deployed)
- **Availability** — manual replica promotion (failover), fencing and rejoin with pg_rewind, health checks
- **Consistency** — CAP/PACELC analysis, synchronous vs asynchronous replication, read-after-write concerns
- **Deployment** — Docker Compose multi-node topology, environment-based configuration

The goal is to demonstrate how ApexBank's core banking ledger can scale beyond a single PostgreSQL instance while preserving financial integrity (double-entry bookkeeping, solvency constraints, append-only history).

---

### 2. Directory Contents & Deliverables

| File | Description |
| :--- | :--- |
| [`docker-compose.distributed.yml`](docker-compose.distributed.yml) | Multi-node PostgreSQL: primary (5435), replica-1 (5436), replica-2 (5437), pgBouncer (6432); replicas self-initialise with `pg_basebackup -R` |
| [`primary-init-replication-hba.sh`](primary-init-replication-hba.sh) | Adds the `pg_hba.conf` rule allowing `replicator` replication connections from the compose network |
| [`primary-init.sql`](primary-init.sql) | Replication user, replication slots, P1 schema + seed load, logical publication (placeholder) |
| [`primary-postgres.conf`](primary-postgres.conf) | Primary postgresql.conf (wal_level=replica, max_wal_senders, wal_log_hints, async replication) |
| [`replica-postgres.conf`](replica-postgres.conf) | Replica postgresql.conf (hot_standby=on) |
| [`pgbouncer.ini`](pgbouncer.ini) | Connection pooler routing to primary + replicas |
| [`userlist.txt`](userlist.txt) | pgBouncer authentication file |
| [`distributed_design.md`](distributed_design.md) | Full design: replication, sharding, availability, consistency, deployment |
| [`replication_setup_and_failover.md`](replication_setup_and_failover.md) | Replica bootstrap, failover/fencing/rejoin procedure, monitoring queries |
| [`distributed_runner.py`](distributed_runner.py) | Python script: replication status and lag, read/write split, pgBouncer pools, sharding routing, consistency checks |
| [`distributed_test_evidence.txt`](distributed_test_evidence.txt) | Raw console output from the runner against the distributed topology |

---

### 3. Architecture Overview

```
+---------------------+      +----------------------+      +----------------------+
|   Client / App      |      |   pgBouncer (6432)   |      |   Health Monitor     |
|  (writes → primary) |      |  (reads → replicas)  |      |   pg_isready checks  |
+---------------------+      +----------------------+      +----------------------+
         |                              |                              |
         |                              v                              |
         |              +----------------+----------------+            |
         |              |      Router      |      Router    |            |
         |              |  (write pool)    |  (read pool)   |            |
         |              +----------------+----------------+            |
         |                              |                              |
+--------v--------+      +-------------v-------------+      +-------------v-------------+
|   PRIMARY       |      |   READ REPLICA 1         |      |   READ REPLICA 2         |
|  (Leader, 5435) |      |  (Hot Standby, 5436)     |      |  (Hot Standby, 5437)     |
|                 |      |                          |      |                          |
| • Accepts writes|      | • Receives streamed WAL  |      | • Receives streamed WAL  |
| • wal_level=replica|     | • hot_standby=on       |      | • hot_standby=on         |
| • Replication slots|     | • Read-only queries    |      | • Read-only queries      |
| • Publishes WAL  |      | • pg_is_in_recovery()=t|      | • pg_is_in_recovery()=t  |
+--------+--------+      +-------------+-------------+      +-------------+-------------+
         |                              |                              |
         |  Streaming Replication (WAL)  |  Streaming Replication (WAL) |
         +------------------------------+------------------------------+
```

---

### 4. Replication Design (Streaming, Physical)

#### 4.1 Topology
- **1 Primary (Leader)**: Accepts all writes; a walsender process per standby streams WAL (physical streaming replication)
- **2 Read Replicas (Hot Standby)**: Bootstrapped by `pg_basebackup -R -S replica_N_slot` (writes `standby.signal` + `primary_conninfo`), then a walreceiver streams and replays WAL; accept read-only queries
- **Replication slots**: `replica_1_slot`, `replica_2_slot` — prevent WAL segment removal before replicas consume it

#### 4.2 Configuration (Primary)
| Setting | Value | Purpose |
| :--- | :--- | :--- |
| `wal_level` | `replica` | Enable WAL logging sufficient for replication |
| `max_wal_senders` | `10` | Max concurrent replication connections |
| `max_replication_slots` | `10` | Persistent WAL retention per replica |
| `wal_keep_size` | `256MB` | Retain WAL for disconnected replicas |
| `wal_log_hints` | `on` | Allows `pg_rewind` of the old primary after failover (image initdb has no data checksums) |
| `synchronous_standby_names` | `''` | **Asynchronous** replication: COMMIT does not wait for any standby (RPO > 0 on failover) |
| `track_commit_timestamp` | `on` | Enable commit timestamp tracking |

#### 4.3 Configuration (Replica)
| Setting | Value | Purpose |
| :--- | :--- | :--- |
| `hot_standby` | `on` | Allow read queries during recovery |
| `hot_standby_feedback` | `on` | Report replica status to primary (avoid VACUUM conflicts) |
| `max_standby_streaming_delay` | `30s` | Max delay before cancelling standby queries |
| `primary_conninfo`, `primary_slot_name` | written by `pg_basebackup -R -S` | Where to stream from and which slot to use (in `postgresql.auto.conf`) |

#### 4.4 Replication User
```sql
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator_dev';
```
The `REPLICATION` attribute allows the user to connect for streaming and identify the system via `IDENTIFY_SYSTEM`.

---

### 5. Sharding Design (Horizontal Partitioning)

ApexBank's transaction volume (millions of daily transfers) exceeds single-node capacity. Sharding distributes data across nodes by account.

#### 5.1 Shard Key: `account_id` (UUID)

All account-centric queries filter by `account_id`, making it the natural shard key:
- Account balance lookups: `WHERE account_id = ?`
- Transaction history: `WHERE source_account_id = ? OR destination_account_id = ?`
- Ledger entries: `WHERE account_id = ?`

#### 5.2 Sharding Strategy: Hash Partitioning

| Shard | Rule | Expected share | Rows co-located with the account |
| :--- | :--- | :--- | :--- |
| Shard A | `account_id` (128-bit int) % 3 == 0 | ~33% | `accounts`, `ledger_entries`, `cards` for that account |
| Shard B | `account_id` (128-bit int) % 3 == 1 | ~33% | as above |
| Shard C | `account_id` (128-bit int) % 3 == 2 | ~33% | as above |

Hashing is name-blind: a shard does not correspond to an alphabetical customer range. The even split relies on random (v4) UUIDs; the hand-written P1 seed UUIDs are not random, so the 8 demo accounts are unevenly spread. Small reference tables (`currencies`, `account_types`) are replicated to every shard.

Each shard runs its own primary + replica pair.

**Trade-offs of the shard key:**
- **Cross-shard transfers.** A P2P transfer debits one account and credits another, so most transfers span two shards (Amina → Chidi does in the runner). Atomicity then needs **two-phase commit** (`PREPARE TRANSACTION` / `COMMIT PREPARED`, `max_prepared_transactions > 0`, an external coordinator, and a plan for orphaned prepared transactions, because 2PC blocks if the coordinator fails) or a **saga** (debit leg, then credit leg, with a compensating REVERSAL journal on failure). The saga gives eventual consistency across shards, and the per-journal double-entry trigger can then only be enforced per shard leg, e.g. against a clearing/suspense account on each shard.
- **Alternative key `customer_id`:** keeps all of a customer's accounts on one shard (own-account transfers stay local) but still splits P2P transfers.
- **Hotspots:** the internal treasury/fee account (`a0000008…`) and large merchant settlement accounts receive a line on almost every journal, so they form a hot shard. Mitigate with per-shard fee/clearing sub-accounts that are swept periodically.
- **Resharding:** plain `% N` moves about (N-1)/N of keys when N changes. Production designs use a fixed number of hash slots/ranges mapped to nodes (consistent hashing; Citus hash ranges) so only some slots move.

#### 5.3 Shard Routing (Application Layer)
```python
def shard_for_account(account_id: uuid.UUID) -> int:
    return int(account_id.int) % 3  # 0, 1, or 2
```
Application routes to the appropriate shard's primary for writes and any of its replicas for reads.

---

### 6. Availability Design

| Failure | Detection | Mitigation |
| :--- | :--- | :--- |
| Primary crashes | `pg_isready` / external monitor (pgBouncer does **not** health-check or fail over) | Promote most up-to-date replica (manual here; Patroni/repmgr in production) |
| Replica crashes | `pg_isready`; slot becomes `active = false` | Application/HAProxy sends reads to the remaining replica; inactive slot retains WAL, so watch disk |
| Network partition | Replication lag monitoring | As configured (async), the primary **keeps accepting writes** and isolated replicas serve stale reads. Blocking writes without a quorum requires synchronous replication (`synchronous_standby_names`) plus a consensus-based failover manager (Patroni + etcd) |
| pgBouncer crash | Container status | No `restart:` policy is set in the lab compose; add `restart: unless-stopped` and run ≥2 poolers behind a load balancer in production |
| WAL backlog | `pg_stat_replication` / `pg_replication_slots` | Alert when `pg_wal_lsn_diff(sent_lsn, replay_lsn)` or slot-retained WAL exceeds a threshold; set `max_slot_wal_keep_size` to cap disk use |

#### 6.1 Failover Procedure
1. Confirm primary is unreachable (`pg_isready` fails on 5435 / `mit8103-pg-primary:5432`) from more than one vantage point
2. **Fence the old primary** (stop the container / revoke its network) so it cannot accept writes. Without fencing, a primary that is only partitioned keeps taking writes and a second primary is promoted: **split-brain**
3. Select most up-to-date replica (highest `pg_last_wal_receive_lsn()` / `pg_last_wal_replay_lsn()`)
4. Promote: `SELECT pg_promote();` (or `pg_ctl promote`). The node switches to a new **timeline** (1 → 2)
5. Repoint the `apexbank` pgBouncer pool / application connection strings to the new primary, then `RELOAD`
6. Repoint the surviving replica's `primary_conninfo` to the new primary (and create a slot there). With `recovery_target_timeline = 'latest'` it follows the new timeline without a fresh base backup, provided it had not replayed past the promotion point
7. Rejoin the old primary as a standby with `pg_rewind` (enabled by `wal_log_hints = on`) or a fresh `pg_basebackup`. Any async-committed transactions that never reached the promoted replica are **lost** (RPO > 0)

---

### 7. Consistency Design (CAP Theorem)

ApexBank must choose between Consistency and Availability during network partitions (P is assumed in distributed systems).

**As deployed** (one primary, two async hot standbys, manual failover), the system is **not** "CA" and not fully "CP":
- **Partition, primary side:** the primary keeps accepting writes, so writes stay available. If an operator then promotes a replica, the un-streamed commits are lost.
- **Partition, replica side:** replicas keep serving reads, which grow stale (available, not consistent). Writes are unavailable on that side.
- **PACELC, normal operation:** async replication chooses Latency over Consistency for replica reads (**PA/EL** for reads). Ledger correctness comes from routing every ledger write and every balance-before-debit read to the single primary.

**Target for the ledger (PC/EC, RPO = 0):** `synchronous_standby_names = 'ANY 1 (replica_1, replica_2)'` with `synchronous_commit = on` (or `remote_apply` for read-your-writes on standbys), plus consensus-based failover (Patroni + etcd) to prevent split-brain. The cost is higher commit latency, and writes block when no standby can acknowledge.

| Scenario | Consistency Level | Rationale |
| :--- | :--- | :--- |
| **Ledger writes (transfers)** | **Strong** (single primary, local ACID commit) | All ledger writes go to one node, so they are serialised there. Replication to standbys is **asynchronous** in this deployment, so durability across nodes is not guaranteed (RPO > 0) |
| **Customer profile reads** | **Eventual** | Profile picture / display name can tolerate replication lag |
| **Transaction history reads** | **Eventual (stale OK)** | Users accept slightly delayed transaction list |
| **Balance checks before debit** | **Strong** (read from primary) | Must read latest balance to prevent overdraft |
| **Idempotency key check** | **Strong** | Must be globally unique to prevent double debit |

#### 7.1 Replication Lag Monitoring
```sql
-- On primary, check replica lag (bytes at each stage, plus measured time lag):
SELECT application_name, state, sync_state,
       pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)   AS send_lag_bytes,
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes,
       write_lag, flush_lag, replay_lag
FROM pg_stat_replication;

-- On a replica:
SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn(),
       now() - pg_last_xact_replay_timestamp() AS approx_replay_delay;
-- (approx_replay_delay grows while the primary is idle; it is not pure lag.)
```

#### 7.2 Read-After-Write Consistency
After a write to the primary, subsequent reads from replicas may be stale. Mitigation:
- **Session pinning**: After a write, direct subsequent reads from the same session to the primary for a configurable window (e.g., 5 seconds)
- **Explicit consistency**: Critical reads (balance check before debit) always go to primary
- **LSN-based read-your-writes**: after COMMIT, record `pg_current_wal_lsn()`; serve the session's next read from a replica only once `pg_last_wal_replay_lsn() >=` that LSN (the runner demonstrates this check), otherwise use the primary
- **`synchronous_commit = remote_apply`** (with synchronous standbys): COMMIT returns only after the standby has applied the WAL, so its reads are current

---

### 8. Deployment (Cloud / Container)

| Component | Deployment | Cloud Equivalent |
| :--- | :--- | :--- |
| PostgreSQL Primary | Docker container + persistent volume | AWS RDS / Azure Database for PostgreSQL / Cloud SQL |
| Read Replicas | Docker containers | RDS Read Replicas / Azure Read Replicas |
| Connection Pooling | pgBouncer container (transaction mode, SCRAM auth) | AWS RDS Proxy / PgBouncer sidecar |
| Service Discovery | Docker DNS / Compose network | Kubernetes Services / AWS Route 53 |
| Orchestration | Docker Compose (dev) | Kubernetes StatefulSets (prod) |
| Monitoring | `pg_stat_replication`, `pg_replication_slots` | CloudWatch / Azure Monitor / Prometheus |

---

### 9. Trade-Off Summary

| Decision | Benefit | Cost / Risk |
| :--- | :--- | :--- |
| Streaming replication (async) | Low write latency, read scale | Replication lag → stale reads on replicas; RPO > 0 on failover |
| Hot standby replicas | Read scale, HA failover | Replicas can lag; split-brain risk on failover |
| Sharding by `account_id` | Horizontal write scale | Cross-shard transactions need 2PC; rebalancing is complex |
| pgBouncer transaction pooling | Connection efficiency; one pool per node | No automatic read/write split or failover; session features (SET, advisory locks, LISTEN, temp tables) unusable; prepared statements need `max_prepared_statements`; adds a hop and a single point of failure (mitigate with multiple) |
| Strong consistency for ledger writes | Financial correctness | With sync replication: lower write availability during partitions and higher commit latency |

---

### 10. Implementation Evidence

`distributed_runner.py` connects to the distributed topology and:
1. Identifies each node's role (primary vs replica via `pg_is_in_recovery()`)
2. Reports sync/async mode, replication slots, `pg_stat_replication` byte and time lag, replica receive/replay LSNs
3. Commits a balanced P1-compliant transfer plus a compensating reversal on the primary, waits for each replica to replay past the commit LSN, and confirms the journal and balance are visible there and that writes are rejected
4. Connects through each pgBouncer pool and reports which backend and role it reached
5. Simulates account-based shard routing (`UUID int % 3`) and flags cross-shard transfers
6. Verifies the double-entry invariant on primary and both replicas
7. Writes `distributed_test_evidence.txt`

Run:
```bash
docker compose -f portfolio-5-distributed-cloud/docker-compose.distributed.yml up -d
pip install -r requirements.txt
python portfolio-5-distributed-cloud/distributed_runner.py
```

Environment:
- `P5_PRIMARY_DSN` (default: `postgresql://apexbank:apexbank_dev@localhost:5435/apexbank`)
- `P5_REPLICA_1_DSN` (default: `postgresql://apexbank:apexbank_dev@localhost:5436/apexbank`)
- `P5_REPLICA_2_DSN` (default: `postgresql://apexbank:apexbank_dev@localhost:5437/apexbank`)
- `P5_PGBOUNCER_DSN` (default: `postgresql://apexbank:apexbank_dev@localhost:6432/apexbank`)

All credentials are development-only lab values.
