"""
MIT 8103 Advanced Database Systems - Portfolio 5
ApexBank Digital Distributed & Cloud Database Exercise

Connects to a multi-node PostgreSQL topology (primary + read replicas) and
demonstrates: node role identification, replication status and lag, read/write
split with replication propagation, pgBouncer pooling, account-based shard
routing, consistency checks and a CAP/PACELC summary.

Usage (from repository root):
    python portfolio-5-distributed-cloud/distributed_runner.py

Environment:
    P5_PRIMARY_DSN     Primary DSN
                       (default: postgresql://apexbank:apexbank_dev@localhost:5435/apexbank)
    P5_REPLICA_1_DSN   Replica 1 DSN
                       (default: postgresql://apexbank:apexbank_dev@localhost:5436/apexbank)
    P5_REPLICA_2_DSN   Replica 2 DSN
                       (default: postgresql://apexbank:apexbank_dev@localhost:5437/apexbank)
    P5_PGBOUNCER_DSN   pgBouncer DSN; the db name is swapped per pool
                       (default: postgresql://apexbank:apexbank_dev@localhost:6432/apexbank)

Note: each run commits a tiny transfer plus its compensating REVERSAL journal
on the primary (append-only ledger => rows are kept; balances net to zero).

Start the topology first:
    docker compose -f portfolio-5-distributed-cloud/docker-compose.distributed.yml up -d
"""

import os
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_PRIMARY = "postgresql://apexbank:apexbank_dev@localhost:5435/apexbank"
DEFAULT_REPLICA_1 = "postgresql://apexbank:apexbank_dev@localhost:5436/apexbank"
DEFAULT_REPLICA_2 = "postgresql://apexbank:apexbank_dev@localhost:5437/apexbank"
DEFAULT_PGBOUNCER = "postgresql://apexbank:apexbank_dev@localhost:6432/apexbank"

PRIMARY_DSN = os.getenv("P5_PRIMARY_DSN", DEFAULT_PRIMARY)
REPLICA_1_DSN = os.getenv("P5_REPLICA_1_DSN", DEFAULT_REPLICA_1)
REPLICA_2_DSN = os.getenv("P5_REPLICA_2_DSN", DEFAULT_REPLICA_2)
PGBOUNCER_DSN = os.getenv("P5_PGBOUNCER_DSN", DEFAULT_PGBOUNCER)

# Real P1 seeded account UUIDs (same as Portfolios 1–4)
ACC_AMINA_USD = "a0000001-0000-4000-8000-000000000001"
ACC_CHIDI_USD = "a0000002-0000-4000-8000-000000000002"

log_output = []


def log(msg=""):
    print(msg)
    log_output.append(msg)


def connect(dsn: str, connect_timeout: int = 3):
    """Best-effort connection; returns None if unavailable."""
    try:
        conn = psycopg.connect(dsn, connect_timeout=connect_timeout)
        conn.autocommit = True
        return conn
    except Exception as exc:  # noqa: BLE001
        log(f"  [CONNECT FAIL] {dsn.split('@')[-1] if '@' in dsn else dsn}: {type(exc).__name__} — {exc}")
        return None


def node_role(conn):
    """Return 'primary' or 'replica' based on pg_is_in_recovery()."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_is_in_recovery();")
            in_recovery = cur.fetchone()[0]
        return "replica" if in_recovery else "primary"
    except Exception:
        return "unknown"


def shard_for_account(account_id_str: str, shard_count: int = 3) -> int:
    """Hash-based shard routing: account_id hash % shard_count."""
    return int(uuid.UUID(account_id_str).int) % shard_count


def main():
    log("=" * 70)
    log("PORTFOLIO 5: DISTRIBUTED & CLOUD DATABASE — APEXBANK DIGITAL")
    log("=" * 70)
    log(f"Primary:   {PRIMARY_DSN.split('@')[-1] if '@' in PRIMARY_DSN else PRIMARY_DSN}")
    log(f"Replica 1: {REPLICA_1_DSN.split('@')[-1] if '@' in REPLICA_1_DSN else REPLICA_1_DSN}")
    log(f"Replica 2: {REPLICA_2_DSN.split('@')[-1] if '@' in REPLICA_2_DSN else REPLICA_2_DSN}")
    log()

    # ------------------------------------------------------------------
    # Connect to all nodes
    # ------------------------------------------------------------------
    log("-" * 70)
    log("1. NODE CONNECTION & ROLE IDENTIFICATION")
    log("-" * 70)

    primary = connect(PRIMARY_DSN)
    replica1 = connect(REPLICA_1_DSN)
    replica2 = connect(REPLICA_2_DSN)

    nodes = [
        ("Primary (Leader)", primary),
        ("Read Replica 1", replica1),
        ("Read Replica 2", replica2),
    ]

    for label, conn in nodes:
        if conn is None:
            log(f"  [{label}] UNAVAILABLE — could not connect")
            continue
        role = node_role(conn)
        log(f"  [{label}] CONNECTED — role={role}")
        if label.startswith("Read Replica") and role != "replica":
            log("             WARNING: node is NOT in recovery — it is a standalone server,")
            log("             not a streaming standby. Recreate the topology (down -v / up -d).")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                log(f"             {cur.fetchone()[0][:60]}...")
        except Exception as exc:  # noqa: BLE001
            log(f"             version query failed: {exc}")
    log()

    # ------------------------------------------------------------------
    # Replication status (on primary)
    # ------------------------------------------------------------------
    log("-" * 70)
    log("2. REPLICATION STATUS (Primary)")
    log("-" * 70)

    if primary is not None:
        try:
            with primary.cursor() as cur:
                cur.execute(
                    "SELECT current_setting('synchronous_standby_names'), "
                    "current_setting('synchronous_commit'), current_setting('wal_level');"
                )
                ssn, sync_commit, wal_level = cur.fetchone()
                mode = "SYNCHRONOUS" if ssn else "ASYNCHRONOUS"
                log(f"  wal_level={wal_level}, synchronous_commit={sync_commit}, "
                    f"synchronous_standby_names='{ssn}' -> {mode} replication")

                # Replication slots
                cur.execute(
                    """
                    SELECT slot_name, slot_type, active,
                           pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
                    FROM pg_replication_slots;
                    """
                )
                slots = cur.fetchall()
                if slots:
                    log("  Replication slots:")
                    for s in slots:
                        log(f"    {s[0]}: type={s[1]}, active={s[2]}, WAL retained for slot={s[3]} bytes")
                else:
                    log("  No replication slots found (replicas may not be streaming)")

                # WAL sender status: byte lag at each stage + time-based lag
                cur.execute(
                    """
                    SELECT application_name, state, sync_state,
                           pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)   AS send_lag_bytes,
                           pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes,
                           write_lag, flush_lag, replay_lag
                    FROM pg_stat_replication
                    ORDER BY application_name;
                    """
                )
                senders = cur.fetchall()
                log(f"  Streaming replicas connected (pg_stat_replication): {len(senders)}")
                for s in senders:
                    log(f"    {s[0]}: state={s[1]}, sync_state={s[2]}, "
                        f"send_lag={s[3]} B, replay_lag={s[4]} B, "
                        f"write_lag={s[5]}, flush_lag={s[6]}, replay_lag_time={s[7]}")
                if not senders:
                    log("  No WAL senders active")
        except Exception as exc:  # noqa: BLE001
            log(f"  Replication status query failed: {exc}")
    else:
        log("  SKIPPED — primary unavailable")

    for label, conn in [("Replica 1", replica1), ("Replica 2", replica2)]:
        if conn is None or node_role(conn) != "replica":
            continue
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn(),
                       pg_last_xact_replay_timestamp(),
                       (SELECT status FROM pg_stat_wal_receiver);
                """
            )
            rcv, rpl, ts, st = cur.fetchone()
            log(f"  [{label}] walreceiver={st}, receive_lsn={rcv}, replay_lsn={rpl}, "
                f"last_replayed_commit={ts}")
    log()

    # ------------------------------------------------------------------
    # Read/write split demonstration
    # ------------------------------------------------------------------
    log("-" * 70)
    log("3. READ/WRITE SPLIT & REPLICATION PROPAGATION")
    log("-" * 70)

    def balance(conn, account_id):
        with conn.cursor() as cur:
            cur.execute("SELECT current_balance FROM accounts WHERE account_id = %s;", (account_id,))
            row = cur.fetchone()
            return row[0] if row else None

    def post_transfer(conn, source, destination, amount, event_type, narrative):
        """Post a balanced 2-line journal in one ACID transaction (P1 rules apply)."""
        ref = f"JRN-P5-{uuid.uuid4().hex[:12].upper()}"
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entries (entry_reference, narrative, event_type)
                    VALUES (%s, %s, %s) RETURNING journal_id;
                    """,
                    (ref, narrative, event_type),
                )
                journal_id = cur.fetchone()[0]
                for acct, entry_type, delta in ((source, "DEBIT", -amount), (destination, "CREDIT", amount)):
                    cur.execute(
                        "SELECT current_balance FROM accounts WHERE account_id = %s FOR UPDATE;",
                        (acct,),
                    )
                    new_bal = cur.fetchone()[0] + delta
                    cur.execute(
                        """
                        INSERT INTO ledger_entries (journal_id, account_id, entry_type, amount, balance_after)
                        VALUES (%s, %s, %s, %s, %s);
                        """,
                        (journal_id, acct, entry_type, amount, new_bal),
                    )
        # WAL insert position after COMMIT: any standby that has replayed up to
        # here is guaranteed to contain this transaction.
        with conn.cursor() as cur:
            cur.execute("SELECT pg_current_wal_lsn();")
            commit_lsn = cur.fetchone()[0]
        return ref, commit_lsn

    written_ref, final_balance, commit_lsn = None, None, None
    if primary is not None:
        try:
            amt = Decimal("0.0100")
            orig_balance = balance(primary, ACC_AMINA_USD)
            log(f"  Primary read before write: Amina balance = {orig_balance}")

            written_ref, _ = post_transfer(
                primary, ACC_AMINA_USD, ACC_CHIDI_USD, amt, "P2P_TRANSFER",
                "P5 replication demo transfer Amina -> Chidi",
            )
            log(f"  Write to primary: journal {written_ref} committed (Amina -> Chidi {amt})")
            log(f"  Primary read after write:  Amina balance = {balance(primary, ACC_AMINA_USD)}")

            rev_ref, commit_lsn = post_transfer(
                primary, ACC_CHIDI_USD, ACC_AMINA_USD, amt, "REVERSAL",
                f"P5 replication demo reversal of {written_ref}",
            )
            final_balance = balance(primary, ACC_AMINA_USD)
            log(f"  Compensating write: journal {rev_ref} committed (Chidi -> Amina {amt}); "
                f"Amina balance = {final_balance} (net zero)")
            log(f"  Primary WAL LSN after commits: {commit_lsn}")
        except Exception as exc:  # noqa: BLE001
            written_ref = None
            log(f"  Write demonstration failed: {exc}")

    # Read from replicas (read-only queries) and measure propagation
    for label, conn in [("Replica 1", replica1), ("Replica 2", replica2)]:
        if conn is None:
            log(f"  [{label}] READ — SKIPPED (unavailable)")
            continue
        try:
            with conn.cursor() as cur:
                if written_ref is not None and node_role(conn) == "replica":
                    # Poll until the replica has replayed past the primary's commit LSN.
                    t0 = time.perf_counter()
                    caught_up = False
                    while time.perf_counter() - t0 < 10:
                        cur.execute("SELECT pg_last_wal_replay_lsn() >= %s::pg_lsn;", (commit_lsn,))
                        if cur.fetchone()[0]:
                            caught_up = True
                            break
                        time.sleep(0.01)
                    waited_ms = (time.perf_counter() - t0) * 1000
                    log(f"  [{label}] replayed past primary LSN {commit_lsn}: {caught_up} "
                        f"(observed propagation <= {waited_ms:.0f} ms)")
                    cur.execute("SELECT count(*) FROM journal_entries WHERE entry_reference = %s;",
                                (written_ref,))
                    log(f"  [{label}] journal {written_ref} visible on replica: {cur.fetchone()[0] == 1}")
                bal = balance(conn, ACC_AMINA_USD)
                match = "" if final_balance is None else f" (matches primary: {bal == final_balance})"
                log(f"  [{label}] READ: Amina balance = {bal}{match}")
                # Confirm read-only: attempts to write should fail
                try:
                    cur.execute(
                        "UPDATE accounts SET current_balance = current_balance WHERE account_id = %s;",
                        (ACC_AMINA_USD,),
                    )
                    log(f"  [{label}] WARNING: write succeeded on replica (not read-only!)")
                except Exception as exc:  # noqa: BLE001
                    log(f"  [{label}] Write correctly blocked on replica: {str(exc).splitlines()[0]}")
        except Exception as exc:  # noqa: BLE001
            log(f"  [{label}] READ failed: {str(exc).splitlines()[0]}")
    log("  Note: async replication => a replica read issued immediately after COMMIT")
    log("  can be stale (no read-your-writes guarantee). The poll above waits for")
    log("  replay; an application would route such reads to the primary instead.")
    log()

    # ------------------------------------------------------------------
    # Connection pooling via pgBouncer
    # ------------------------------------------------------------------
    log("-" * 70)
    log("4. CONNECTION POOLING (pgBouncer, transaction mode)")
    log("-" * 70)
    for pool_db in ("apexbank", "apexbank_replica_1", "apexbank_replica_2"):
        dsn = PGBOUNCER_DSN.rsplit("/", 1)[0] + "/" + pool_db
        try:
            # prepare_threshold=None: no server-side prepared statements via the pooler
            with psycopg.connect(dsn, connect_timeout=3, autocommit=True, prepare_threshold=None) as pc:
                with pc.cursor() as cur:
                    cur.execute("SELECT pg_is_in_recovery(), inet_server_addr()::text;")
                    rec, addr = cur.fetchone()
                    log(f"  pgBouncer pool '{pool_db}' -> backend {addr} "
                        f"role={'replica' if rec else 'primary'}")
        except Exception as exc:  # noqa: BLE001
            log(f"  pgBouncer pool '{pool_db}' unavailable: {type(exc).__name__} — "
                f"{str(exc).splitlines()[0] if str(exc) else ''}")
    log()

    # ------------------------------------------------------------------
    # Sharding demonstration
    # ------------------------------------------------------------------
    log("-" * 70)
    log("5. ACCOUNT-BASED SHARDING DEMONSTRATION (routing simulation)")
    log("-" * 70)
    log("  Shard routing: shard = UUID(account_id) as 128-bit integer % 3")

    test_accounts = [
        ACC_AMINA_USD,
        ACC_CHIDI_USD,
        "a0000005-0000-4000-8000-000000000005",
        "a0000008-0000-4000-8000-000000000008",
    ]
    for acct in test_accounts:
        shard = shard_for_account(acct)
        log(f"  Account {acct} -> Shard {shard}")
    log("  Deterministic: the same account_id always routes to the same shard.")
    if shard_for_account(ACC_AMINA_USD) != shard_for_account(ACC_CHIDI_USD):
        log("  Amina -> Chidi transfer is CROSS-SHARD: needs 2PC (PREPARE TRANSACTION /")
        log("  COMMIT PREPARED, max_prepared_transactions > 0) or a saga with compensating")
        log("  journals; one shard's local transaction cannot make both legs atomic.")
    log()

    # ------------------------------------------------------------------
    # Consistency checks
    # ------------------------------------------------------------------
    log("-" * 70)
    log("6. CONSISTENCY CHECKS")
    log("-" * 70)

    for label, conn in [("Primary", primary), ("Replica 1", replica1), ("Replica 2", replica2)]:
        if conn is None:
            continue
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM accounts;")
                acct_count = cur.fetchone()[0]

                # Verify double-entry invariant per journal (P1 constraint)
                cur.execute(
                    """
                    SELECT j.journal_id,
                           SUM(CASE WHEN le.entry_type = 'DEBIT' THEN le.amount ELSE 0 END) AS debits,
                           SUM(CASE WHEN le.entry_type = 'CREDIT' THEN le.amount ELSE 0 END) AS credits
                    FROM journal_entries j
                    JOIN ledger_entries le ON le.journal_id = j.journal_id
                    GROUP BY j.journal_id;
                    """
                )
                journals = cur.fetchall()
                balanced = all(row[1] == row[2] for row in journals)
                log(f"  [{label}] accounts={acct_count}, journals={len(journals)}, all balanced: {balanced}")
        except Exception as exc:  # noqa: BLE001
            log(f"  [{label}] consistency check failed: {str(exc).splitlines()[0]}")
    log("  Ledger invariants are enforced once, on the single primary; standbys are")
    log("  physical (block-level) copies, so they inherit the same invariants.")
    log()

    # ------------------------------------------------------------------
    # CAP / PACELC summary
    # ------------------------------------------------------------------
    log("-" * 70)
    log("7. CAP / PACELC ANALYSIS (as configured)")
    log("-" * 70)
    log("  Topology: single primary + 2 ASYNC hot standbys, manual failover.")
    log("  Partition (P), primary side: primary keeps accepting writes (available);")
    log("     replicas cut off from it keep serving reads that grow stale.")
    log("  Partition, replica side: reads stay available but are not linearizable;")
    log("     writes are unavailable there (standbys are read-only).")
    log("  Else (E, no partition): async replication trades replica consistency for")
    log("     commit latency => PACELC PA/EL for replica reads.")
    log("  Ledger correctness comes from routing ALL ledger writes and balance-before-")
    log("     debit reads to the one primary (single-node ACID), not from replication.")
    log("  Failover RPO > 0 while async: commits not yet streamed are lost on promotion.")
    log("  Target for ledger (PC/EC, RPO=0): synchronous_standby_names =")
    log("     'ANY 1 (replica_1, replica_2)' — writes block rather than risk loss.")
    log()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    for conn in (primary, replica1, replica2):
        if conn is not None:
            conn.close()

    log("=" * 70)
    log("PORTFOLIO 5 RUN COMPLETE")
    log("=" * 70)

    evidence_path = BASE_DIR / "distributed_test_evidence.txt"
    evidence_path.write_text("\n".join(log_output), encoding="utf-8")
    print()
    print(f"[OK] Evidence written to: {evidence_path}")


if __name__ == "__main__":
    main()
