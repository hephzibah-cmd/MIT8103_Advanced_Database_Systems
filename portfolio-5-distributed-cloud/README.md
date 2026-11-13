# Portfolio 5: Distributed and Cloud Database Exercise
**Course:** MIT 8103 Advanced Database Systems  
**Case Study:** ApexBank Digital (Next-Generation Digital Banking & Fintech Platform)  
**Database Engine:** PostgreSQL 16 (Primary + Read Replicas)  
**Marks Allocated:** 6 Marks  
**Schema Source:** Portfolio 1 (`../portfolio-1-database-design/ddl_schema.sql`, `seed_data.sql`)

---

### Executive Summary

Portfolio 5 extends the ApexBank Digital case study into **distributed and cloud database architecture**. Building on the Portfolio 1 relational schema (PostgreSQL 16), this portfolio designs and implements a multi-node deployment featuring streaming replication, read/write splitting, connection pooling, sharding design, availability failover procedures, and CAP theorem consistency analysis — all applied to the ApexBank Digital core banking ledger.

---

### Directory Contents & Deliverables

| File | Description |
| :--- | :--- |
| [`docker-compose.distributed.yml`](docker-compose.distributed.yml) | Multi-node PostgreSQL: primary (5435), replica-1 (5436), replica-2 (5437), pgBouncer (6432); replicas self-bootstrap via `pg_basebackup -R` |
| [`primary-init-replication-hba.sh`](primary-init-replication-hba.sh) | Adds the `pg_hba.conf` rule allowing replication connections for `replicator` |
| [`primary-init.sql`](primary-init.sql) | Replication user, replication slots, P1 schema + seed load (deferred-constraint safe), logical publication (placeholder; needs `wal_level=logical`) |
| [`primary-postgres.conf`](primary-postgres.conf) | Primary postgresql.conf (wal_level=replica, max_wal_senders, wal_log_hints, async replication) |
| [`replica-postgres.conf`](replica-postgres.conf) | Replica postgresql.conf (hot_standby=on) |
| [`pgbouncer.ini`](pgbouncer.ini) | Connection pooler: one transaction-mode pool per node, SCRAM auth |
| [`userlist.txt`](userlist.txt) | pgBouncer authentication file (dev-only plaintext password) |
| [`distributed_design.md`](distributed_design.md) | Full design: replication, sharding, availability, consistency, deployment |
| [`replication_setup_and_failover.md`](replication_setup_and_failover.md) | Replica initialization via pg_basebackup, primary failover procedure, monitoring queries |
| [`distributed_runner.py`](distributed_runner.py) | Python script: node roles, replication status and lag, read/write split with replication propagation, pgBouncer pools, shard routing, consistency checks, CAP/PACELC analysis |
| [`distributed_test_evidence.txt`](distributed_test_evidence.txt) | Raw console output from the runner against the distributed topology |

---

### Distributed Architecture

| Component | Role | Host Port | Container Port |
| :--- | :--- | :--- | :--- |
| `mit8103-pg-primary` | Leader — accepts writes, streams WAL | 5435 | 5432 |
| `mit8103-pg-replica-1` | Hot standby — read-only, streams from primary | 5436 | 5432 |
| `mit8103-pg-replica-2` | Hot standby — read-only, streams from primary | 5437 | 5432 |
| `mit8103-pgbouncer` | Connection pooler / load balancer | 6432 | 6432 |

---

### Setup & Run

From the repository root:

```bash
# 1. Start the distributed PostgreSQL topology
docker compose -f portfolio-5-distributed-cloud/docker-compose.distributed.yml up -d

#    (after any config change: `down -v` first; replicas only bootstrap on an empty volume)
# 2. Wait for all containers to be healthy
docker compose -f portfolio-5-distributed-cloud/docker-compose.distributed.yml ps

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Run Portfolio 5
python portfolio-5-distributed-cloud/distributed_runner.py
```

Environment variables (optional):

```powershell
$env:P5_PRIMARY_DSN="postgresql://apexbank:apexbank_dev@localhost:5435/apexbank"
$env:P5_REPLICA_1_DSN="postgresql://apexbank:apexbank_dev@localhost:5436/apexbank"
$env:P5_REPLICA_2_DSN="postgresql://apexbank:apexbank_dev@localhost:5437/apexbank"
$env:P5_PGBOUNCER_DSN="postgresql://apexbank:apexbank_dev@localhost:6432/apexbank"
```

All passwords in this folder (`apexbank_dev`, `replicator_dev`) are development-only lab credentials.

What the runner does:

1. **Node connection & role identification** — connects to all 3 nodes, identifies each as primary or replica via `pg_is_in_recovery()`
2. **Replication status** — sync/async mode, `pg_replication_slots`, `pg_stat_replication` byte and time lag, replica receive/replay LSNs
3. **Read/write split demonstration** — commits a balanced transfer and a compensating reversal on the primary (net-zero balance, but two journals are appended per run), waits until each replica has replayed past the commit LSN, reads the result there, and shows writes are rejected on replicas
4. **Connection pooling** — connects through each pgBouncer pool and reports the backend role reached
5. **Account-based sharding** — simulates `UUID(account_id) % 3` routing and flags cross-shard transfers
6. **Consistency checks** — verifies double-entry journal balance on the primary and both replicas
7. **CAP/PACELC analysis** of the deployed (async) configuration
8. Writes `distributed_test_evidence.txt`

---

### Relationship to Portfolio 1

- **Same case study:** ApexBank Digital, same entities (customers, accounts, cards, transactions, ledger_entries, journal_entries)
- **Same data:** Primary loads P1 schema (`ddl_schema.sql`) and seed data (`seed_data.sql`) verbatim — 8 accounts, 2 balanced journals, 2 transactions
- **Same constraints:** Deferred double-entry triggers, `chk_account_solvency`, append-only ledger/journal, idempotency uniqueness all enforced on the primary
- **Extension:** Adds distributed concepts (replication, sharding, connection pooling, failover, CAP analysis) on top of the P1 relational foundation

---

### Key Design Decisions

| Decision | Rationale |
| :--- | :--- |
| **Streaming replication (physical)** | Native PostgreSQL feature, low overhead, WAL-based |
| **1 primary + 2 read replicas** | Write scalability (single primary for consistency), read scale (2 replicas), HA failover target |
| **Asynchronous replication (default)** | Lowest commit latency. Trade-off: RPO > 0 on failover and stale replica reads; synchronous quorum is the documented upgrade path for the ledger |
| **Physical replication slots** | Prevents WAL segment removal before replicas consume it |
| **Sharding by `account_id` hash (design)** | Account-centric queries dominate; even distribution. Cost: P2P transfers become cross-shard (2PC or saga), treasury/fee account is a hotspot |
| **pgBouncer transaction pooling** | Connection efficiency; one pool per node, application chooses (no automatic read/write split or failover) |
| **Ledger on primary only; replicas for stale-tolerant reads** | Ledger writes and balance-before-debit reads are strongly consistent because one node serialises them. As deployed (async), the cluster is PA/EL for replica reads; CP for the ledger needs synchronous replication plus fenced failover |

---

### File Links

Use relative links only:
- `docker-compose.distributed.yml`
- `primary-init-replication-hba.sh`
- `primary-init.sql`
- `primary-postgres.conf`
- `replica-postgres.conf`
- `pgbouncer.ini`
- `userlist.txt`
- `distributed_design.md`
- `replication_setup_and_failover.md`
- `distributed_runner.py`
- `distributed_test_evidence.txt`
- `../portfolio-1-database-design/ddl_schema.sql`
- `../portfolio-1-database-design/seed_data.sql`
