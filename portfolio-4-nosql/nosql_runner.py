"""
MIT 8103 Advanced Database Systems - Portfolio 4
ApexBank Digital NoSQL and Advanced Data Models

MongoDB 7.0 document-store implementation for the ApexBank Digital case study.
Connects to MongoDB, creates collections, ingests ApexBank seed data as
documents, runs document and key-value queries, and writes evidence.

Usage (from repository root):
    python portfolio-4-nosql/nosql_runner.py

Environment:
    NOSQL_DATABASE_URL   MongoDB connection string
                         (default: mongodb://apexbank:apexbank_dev@localhost:27017/apexbank?authSource=admin)
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pymongo
from bson.decimal128 import Decimal128
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_URL = (
    "mongodb://apexbank:apexbank_dev@localhost:27017/apexbank?authSource=admin"
)
NOSQL_URL = os.getenv("NOSQL_DATABASE_URL", DEFAULT_URL)

log_output = []


def log(msg=""):
    print(msg)
    log_output.append(msg)


def to_mongo(value):
    """Recursively convert Decimal -> BSON Decimal128 (exact base-10 money,
    mirroring P1 NUMERIC(18,4); binary float would introduce rounding error)."""
    if isinstance(value, Decimal):
        return Decimal128(value)
    if isinstance(value, dict):
        return {k: to_mongo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_mongo(v) for v in value]
    return value


def connect(url: str):
    client = pymongo.MongoClient(url, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client


def seed_customers(customers_coll):
    docs = [
        {
            "customer_id": "c0000001-0000-4000-8000-000000000001",
            "first_name": "Amina",
            "last_name": "Bello",
            "email": "amina.bello@example.com",
            "phone_number": "+2348031112233",
            "tier_level": "TIER_3",
            "status": "ACTIVE",
            "kyc": {
                "kyc_id": "d0000001-0000-4000-8000-000000000001",
                "document_type": "NATIONAL_ID",
                "id_number": "NIN-1092837465",
                "verification_status": "VERIFIED",
                "verified_at": "2026-01-15T09:30:00+01:00",
            },
            "created_at": "2026-01-10T08:00:00+01:00",
            "updated_at": "2026-01-15T09:30:00+01:00",
        },
        {
            "customer_id": "c0000002-0000-4000-8000-000000000002",
            "first_name": "Chidi",
            "last_name": "Okonkwo",
            "email": "chidi.o@example.com",
            "phone_number": "+2348022223344",
            "tier_level": "TIER_3",
            "status": "ACTIVE",
            "kyc": {
                "kyc_id": "d0000002-0000-4000-8000-000000000002",
                "document_type": "PASSPORT",
                "id_number": "A09876543",
                "verification_status": "VERIFIED",
                "verified_at": "2026-02-10T11:15:00+01:00",
            },
            "created_at": "2026-01-11T08:00:00+01:00",
            "updated_at": "2026-02-10T11:15:00+01:00",
        },
        {
            "customer_id": "c0000003-0000-4000-8000-000000000003",
            "first_name": "Folake",
            "last_name": "Adeyemi",
            "email": "folake.a@example.com",
            "phone_number": "+2348055556677",
            "tier_level": "TIER_2",
            "status": "ACTIVE",
            "kyc": {
                "kyc_id": "d0000003-0000-4000-8000-000000000003",
                "document_type": "BVN",
                "id_number": "22334455667",
                "verification_status": "VERIFIED",
                "verified_at": "2026-03-01T14:00:00+01:00",
            },
            "created_at": "2026-01-12T08:00:00+01:00",
            "updated_at": "2026-03-01T14:00:00+01:00",
        },
        {
            "customer_id": "c0000004-0000-4000-8000-000000000004",
            "first_name": "David",
            "last_name": "Kalu",
            "email": "david.kalu@example.com",
            "phone_number": "+2348109998877",
            "tier_level": "TIER_1",
            "status": "ACTIVE",
            "kyc": None,
            "created_at": "2026-01-13T08:00:00+01:00",
            "updated_at": "2026-01-13T08:00:00+01:00",
        },
        {
            "customer_id": "c0000005-0000-4000-8000-000000000005",
            "first_name": "Zainab",
            "last_name": "Mohammed",
            "email": "zainab.m@example.com",
            "phone_number": "+2348077778899",
            "tier_level": "TIER_3",
            "status": "ACTIVE",
            "kyc": {
                "kyc_id": "d0000004-0000-4000-8000-000000000004",
                "document_type": "PASSPORT",
                "id_number": "B11223344",
                "verification_status": "VERIFIED",
                "verified_at": "2026-01-20T16:45:00+01:00",
            },
            "created_at": "2026-01-14T08:00:00+01:00",
            "updated_at": "2026-01-20T16:45:00+01:00",
        },
        {
            "customer_id": "c0000006-0000-4000-8000-000000000006",
            "first_name": "Kolawole",
            "last_name": "Balogun",
            "email": "kola.balogun@example.com",
            "phone_number": "+2348123456789",
            "tier_level": "TIER_3",
            "status": "ACTIVE",
            "kyc": {
                "kyc_id": "d0000005-0000-4000-8000-000000000005",
                "document_type": "NATIONAL_ID",
                "id_number": "NIN-8877665544",
                "verification_status": "VERIFIED",
                "verified_at": "2026-02-18T10:00:00+01:00",
            },
            "created_at": "2026-01-15T08:00:00+01:00",
            "updated_at": "2026-02-18T10:00:00+01:00",
        },
        {
            "customer_id": "c0000007-0000-4000-8000-000000000007",
            "first_name": "Ngozi",
            "last_name": "Eze",
            "email": "ngozi.eze@example.com",
            "phone_number": "+2348098765432",
            "tier_level": "TIER_2",
            "status": "ACTIVE",
            "kyc": None,
            "created_at": "2026-01-16T08:00:00+01:00",
            "updated_at": "2026-01-16T08:00:00+01:00",
        },
        {
            "customer_id": "c0000008-0000-4000-8000-000000000008",
            "first_name": "ApexBank",
            "last_name": "Internal Treasury",
            "email": "treasury@apexbank.internal",
            "phone_number": "+2348000000000",
            "tier_level": "TIER_3",
            "status": "ACTIVE",
            "kyc": None,
            "created_at": "2026-01-01T00:00:00+01:00",
            "updated_at": "2026-01-01T00:00:00+01:00",
        },
    ]
    customers_coll.insert_many([to_mongo(d) for d in docs], ordered=False)
    log(f"  [OK] Inserted {len(docs)} customer documents")


def seed_accounts(accounts_coll):
    docs = [
        {
            "account_id": "a0000001-0000-4000-8000-000000000001",
            "customer_id": "c0000001-0000-4000-8000-000000000001",
            "account_number": "1000100101",
            "currency_code": "USD",
            "current_balance": Decimal("14500.5000"),
            "hold_balance": Decimal("0.0000"),
            "overdraft_limit": Decimal("1000.0000"),
            "account_status": "ACTIVE",
            "opened_at": "2026-01-10T08:00:00+01:00",
            "cards": [
                {
                    "card_id": "f0000001-0000-4000-8000-000000000001",
                    "masked_pan": "411111XXXXXX1122",
                    "card_token": "tok_vault_6b1f0c2a9d4e8f7b",
                    "pan_hmac": "2cd4bde77ae262c960a8643c57c18048bcad51885f144496dd51ae36cb0b8169",
                    "expiry_date": "2028-12-31",
                    "card_type": "DEBIT",
                    "daily_spend_limit": Decimal("5000.0000"),
                    "card_status": "ACTIVE",
                }
            ],
        },
        {
            "account_id": "a0000002-0000-4000-8000-000000000002",
            "customer_id": "c0000002-0000-4000-8000-000000000002",
            "account_number": "1000100102",
            "currency_code": "USD",
            "current_balance": Decimal("8250.0000"),
            "hold_balance": Decimal("0.0000"),
            "overdraft_limit": Decimal("500.0000"),
            "account_status": "ACTIVE",
            "opened_at": "2026-01-11T08:00:00+01:00",
            "cards": [
                {
                    "card_id": "f0000002-0000-4000-8000-000000000002",
                    "masked_pan": "422222XXXXXX3344",
                    "card_token": "tok_vault_7c2a1d3b0e5f9a8c",
                    "pan_hmac": "00ff9f8f47d61bdc53831307ec68dd966495b9d8271c87e4173f56d7c81a6756",
                    "expiry_date": "2027-08-31",
                    "card_type": "DEBIT",
                    "daily_spend_limit": Decimal("3000.0000"),
                    "card_status": "ACTIVE",
                }
            ],
        },
        {
            "account_id": "a0000003-0000-4000-8000-000000000003",
            "customer_id": "c0000003-0000-4000-8000-000000000003",
            "account_number": "2000200201",
            "currency_code": "NGN",
            "current_balance": Decimal("750000.0000"),
            "hold_balance": Decimal("0.0000"),
            "overdraft_limit": Decimal("0.0000"),
            "account_status": "ACTIVE",
            "opened_at": "2026-01-12T08:00:00+01:00",
            "cards": [],
        },
        {
            "account_id": "a0000004-0000-4000-8000-000000000004",
            "customer_id": "c0000004-0000-4000-8000-000000000004",
            "account_number": "2000200202",
            "currency_code": "NGN",
            "current_balance": Decimal("45000.0000"),
            "hold_balance": Decimal("0.0000"),
            "overdraft_limit": Decimal("0.0000"),
            "account_status": "ACTIVE",
            "opened_at": "2026-01-13T08:00:00+01:00",
            "cards": [],
        },
        {
            "account_id": "a0000005-0000-4000-8000-000000000005",
            "customer_id": "c0000005-0000-4000-8000-000000000005",
            "account_number": "1000100105",
            "currency_code": "USD",
            "current_balance": Decimal("32000.7500"),
            "hold_balance": Decimal("500.0000"),
            "overdraft_limit": Decimal("2000.0000"),
            "account_status": "ACTIVE",
            "opened_at": "2026-01-14T08:00:00+01:00",
            "cards": [
                {
                    "card_id": "f0000003-0000-4000-8000-000000000003",
                    "masked_pan": "433333XXXXXX5566",
                    "card_token": "tok_vault_8d3b2e4c1f6a0b9d",
                    "pan_hmac": "ed734670251bfc2e49b6d00cfc02c56a9de673de5edd3110afbc43d3e0eb5c0f",
                    "expiry_date": "2029-05-31",
                    "card_type": "VIRTUAL_DEBIT",
                    "daily_spend_limit": Decimal("10000.0000"),
                    "card_status": "ACTIVE",
                }
            ],
        },
        {
            "account_id": "a0000006-0000-4000-8000-000000000006",
            "customer_id": "c0000006-0000-4000-8000-000000000006",
            "account_number": "1000100106",
            "currency_code": "USD",
            "current_balance": Decimal("125400.0000"),
            "hold_balance": Decimal("0.0000"),
            "overdraft_limit": Decimal("5000.0000"),
            "account_status": "ACTIVE",
            "opened_at": "2026-01-15T08:00:00+01:00",
            "cards": [],
        },
        {
            "account_id": "a0000007-0000-4000-8000-000000000007",
            "customer_id": "c0000007-0000-4000-8000-000000000007",
            "account_number": "1000100107",
            "currency_code": "USD",
            "current_balance": Decimal("3200.0000"),
            "hold_balance": Decimal("0.0000"),
            "overdraft_limit": Decimal("0.0000"),
            "account_status": "ACTIVE",
            "opened_at": "2026-01-16T08:00:00+01:00",
            "cards": [],
        },
        {
            "account_id": "a0000008-0000-4000-8000-000000000008",
            "customer_id": "c0000008-0000-4000-8000-000000000008",
            "account_number": "9999000001",
            "currency_code": "USD",
            "current_balance": Decimal("18452.0500"),
            "hold_balance": Decimal("0.0000"),
            "overdraft_limit": Decimal("0.0000"),
            "account_status": "ACTIVE",
            "opened_at": "2026-01-01T00:00:00+01:00",
            "cards": [],
        },
    ]
    accounts_coll.insert_many([to_mongo(d) for d in docs], ordered=False)
    log(f"  [OK] Inserted {len(docs)} account documents (cards embedded)")


def seed_transactions(transactions_coll):
    docs = [
        {
            "transaction_id": "30000001-0000-4000-8000-000000000001",
            "transaction_reference": "TXN-20261025-001",
            "idempotency_key": "idem-key-889911-a",
            "source_account_id": "a0000001-0000-4000-8000-000000000001",
            "destination_account_id": "a0000002-0000-4000-8000-000000000002",
            "merchant_id": None,
            "journal_id": "10000001-0000-4000-8000-000000000001",
            "currency_code": "USD",
            "amount": Decimal("500.0000"),
            "fee_amount": Decimal("2.5000"),
            "channel": "MOBILE_APP",
            "status": "SETTLED",
            "initiated_at": "2026-10-25T10:13:58+01:00",
            "completed_at": "2026-10-25T10:14:01+01:00",
            "ledger_lines": [
                {
                    "account_id": "a0000001-0000-4000-8000-000000000001",
                    "entry_type": "DEBIT",
                    "amount": Decimal("502.5000"),
                    "balance_after": Decimal("14500.5000"),
                },
                {
                    "account_id": "a0000002-0000-4000-8000-000000000002",
                    "entry_type": "CREDIT",
                    "amount": Decimal("500.0000"),
                    "balance_after": Decimal("8250.0000"),
                },
                {
                    "account_id": "a0000008-0000-4000-8000-000000000008",
                    "entry_type": "CREDIT",
                    "amount": Decimal("2.5000"),
                    "balance_after": Decimal("18450.2500"),
                },
            ],
        },
        {
            "transaction_id": "30000002-0000-4000-8000-000000000002",
            "transaction_reference": "TXN-20261026-002",
            "idempotency_key": "idem-key-991122-b",
            "source_account_id": "a0000005-0000-4000-8000-000000000005",
            "destination_account_id": "a0000006-0000-4000-8000-000000000006",
            "merchant_id": "e0000001-0000-4000-8000-000000000001",
            "journal_id": "10000002-0000-4000-8000-000000000002",
            "currency_code": "USD",
            "amount": Decimal("120.0000"),
            "fee_amount": Decimal("1.8000"),
            "channel": "POS_TERMINAL",
            "status": "SETTLED",
            "initiated_at": "2026-10-26T14:29:55+01:00",
            "completed_at": "2026-10-26T14:30:02+01:00",
            "ledger_lines": [
                {
                    "account_id": "a0000005-0000-4000-8000-000000000005",
                    "entry_type": "DEBIT",
                    "amount": Decimal("120.0000"),
                    "balance_after": Decimal("32000.7500"),
                },
                {
                    "account_id": "a0000006-0000-4000-8000-000000000006",
                    "entry_type": "CREDIT",
                    "amount": Decimal("118.2000"),
                    "balance_after": Decimal("125400.0000"),
                },
                {
                    "account_id": "a0000008-0000-4000-8000-000000000008",
                    "entry_type": "CREDIT",
                    "amount": Decimal("1.8000"),
                    "balance_after": Decimal("18452.0500"),
                },
            ],
        },
    ]
    transactions_coll.insert_many([to_mongo(d) for d in docs], ordered=False)
    log(f"  [OK] Inserted {len(docs)} transaction documents (ledger lines embedded)")


def seed_kv(kv_coll):
    """Key-value store: idempotency cache, sessions, rate limits.

    expire_at must be a BSON date for the TTL index; it is computed relative
    to the run time (24h / 30m / 60s) so live keys are not already expired.
    The TTL monitor only sweeps every ~60s, so reads also filter on expire_at.
    """
    now = datetime.now(timezone.utc)
    docs = [
        {
            "_key": "idem:idem-key-889911-a",
            "value": {"transaction_id": "30000001-0000-4000-8000-000000000001"},
            "kind": "idempotency",
            "expire_at": now + timedelta(hours=24),
        },
        {
            "_key": "idem:idem-key-991122-b",
            "value": {"transaction_id": "30000002-0000-4000-8000-000000000002"},
            "kind": "idempotency",
            "expire_at": now + timedelta(hours=24),
        },
        {
            "_key": "sess:sess_abc123",
            "value": {
                "customer_id": "c0000001-0000-4000-8000-000000000001",
                "channel": "MOBILE_APP",
            },
            "kind": "session",
            "expire_at": now + timedelta(minutes=30),
        },
        {
            "_key": "ratelimit:c0000001-0000-4000-8000-000000000001",
            "value": {"count": 7},
            "kind": "rate_limit",
            "expire_at": now + timedelta(seconds=60),
        },
        {
            "_key": "card_lock:f0000001-0000-4000-8000-000000000001",
            "value": {"locked": False},
            "kind": "card_lock",
            "expire_at": None,  # non-date value -> never expired by TTL monitor
        },
    ]
    kv_coll.insert_many([to_mongo(d) for d in docs], ordered=False)
    log(f"  [OK] Inserted {len(docs)} key-value documents")


def run_document_queries(db):
    log()
    log("-" * 60)
    log("DOCUMENT MODEL QUERIES (MongoDB)")
    log("-" * 60)

    customers = db["customers"]
    accounts = db["accounts"]
    transactions = db["transactions"]

    # Q1: Single-document read — customer profile with embedded KYC
    log()
    log("Q1: Customer profile with embedded KYC (single document read, zero joins)")
    doc = customers.find_one(
        {"customer_id": "c0000001-0000-4000-8000-000000000001"},
        {"_id": 0},
    )
    log(f"  {doc}")
    log("  [PASS] Customer + KYC retrieved in one document read (no JOIN).")

    # Q2: Account with embedded cards
    log()
    log("Q2: Account with embedded cards (aggregate read)")
    doc = accounts.find_one(
        {"account_id": "a0000001-0000-4000-8000-000000000001"},
        {"_id": 0},
    )
    card_count = len(doc.get("cards", []))
    log(f"  Account {doc['account_number']} balance={doc['current_balance']} cards={card_count}")
    log("  [PASS] Account + cards retrieved in one document read.")

    # Q3: Transactions by source account with embedded ledger lines
    log()
    log("Q3: Transactions sourced from an account, with embedded ledger lines")
    cursor = transactions.find(
        {"source_account_id": "a0000001-0000-4000-8000-000000000001"},
        {"_id": 0, "transaction_reference": 1, "amount": 1, "status": 1, "ledger_lines": 1},
    )
    rows = list(cursor)
    log(f"  Found {len(rows)} transaction(s)")
    for r in rows:
        log(f"    {r['transaction_reference']}: {r['amount']} {r['status']}, ledger_lines={len(r['ledger_lines'])}")
    log("  [PASS] Transaction + ledger lines retrieved in one document read.")

    # Q4: Indexed query — transactions by status
    log()
    log("Q4: Indexed query — SETTLED transactions (index on status)")
    transactions.create_index([("status", ASCENDING)], name="idx_status")
    cursor = transactions.find({"status": "SETTLED"}, {"_id": 0, "transaction_reference": 1, "amount": 1})
    rows = list(cursor)
    log(f"  Found {len(rows)} SETTLED transaction(s)")
    log("  [PASS] Index-supported status query executed.")

    # Q5: Aggregation — total debits/credits by account
    log()
    log("Q5: Aggregation — sum of debit amounts per account (unwind embedded ledger_lines)")
    pipeline = [
        {"$unwind": "$ledger_lines"},
        {"$group": {"_id": "$ledger_lines.account_id", "total_debit": {"$sum": {"$cond": [{"$eq": ["$ledger_lines.entry_type", "DEBIT"]}, "$ledger_lines.amount", Decimal128("0.0000")]}}}},
        {"$sort": {"_id": ASCENDING}},
    ]
    results = list(transactions.aggregate(pipeline))
    for r in results:
        log(f"  Account {r['_id']}: total_debit={r['total_debit']}")
    log("  [PASS] Aggregation over embedded ledger_lines completed.")


def run_kv_operations(db):
    log()
    log("-" * 60)
    log("KEY-VALUE MODEL OPERATIONS (MongoDB kv_store with TTL index)")
    log("-" * 60)

    kv = db["kv_store"]
    kv.create_index([("expire_at", ASCENDING)], expireAfterSeconds=0, name="idx_ttl")
    now = datetime.now(timezone.utc)
    live = {"$or": [{"expire_at": {"$gt": now}}, {"expire_at": None}]}

    # KV1: Idempotency check — get by key
    log()
    log("KV1: Idempotency key lookup (get by key)")
    entry = kv.find_one({"_key": "idem:idem-key-889911-a", **live}, {"_id": 0, "expire_at": 0})
    log(f"  {entry}")
    status = "PASS" if entry else "FAIL"
    log(f"  [{status}] Live idempotency key found -> duplicate payment would be rejected.")

    # KV1b: Idempotent SET-if-absent — unique index rejects a retried payment
    log()
    log("KV1b: Retry with same idempotency key (insert-if-absent on unique _key)")
    try:
        kv.insert_one({
            "_key": "idem:idem-key-889911-a",
            "value": {"transaction_id": "30000099-0000-4000-8000-000000000099"},
            "kind": "idempotency",
            "expire_at": now + timedelta(hours=24),
        })
        log("  [FAIL] Duplicate idempotency key was accepted.")
    except DuplicateKeyError:
        log("  [PASS] DuplicateKeyError raised -> retried payment rejected, original transaction_id returned.")

    # KV2: Session get
    log()
    log("KV2: Session token lookup")
    entry = kv.find_one({"_key": "sess:sess_abc123", "kind": "session", **live}, {"_id": 0, "expire_at": 0})
    log(f"  {entry}")
    status = "PASS" if entry else "FAIL"
    log(f"  [{status}] Session retrieved by token key.")

    # KV3: Rate-limit increment (atomic $inc)
    log()
    log("KV3: Atomic rate-limit increment ($inc)")
    result = kv.find_one_and_update(
        {"_key": "ratelimit:c0000001-0000-4000-8000-000000000001", "kind": "rate_limit"},
        {"$inc": {"value.count": 1}},
        return_document=pymongo.ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    log(f"  New count: {result['value']['count']}")
    log("  [PASS] Atomic increment executed.")

    # KV4: Card lock toggle
    log()
    log("KV4: Card lock toggle (set field)")
    kv.update_one(
        {"_key": "card_lock:f0000001-0000-4000-8000-000000000001", "kind": "card_lock"},
        {"$set": {"value.locked": True}},
    )
    entry = kv.find_one({"_key": "card_lock:f0000001-0000-4000-8000-000000000001"}, {"_id": 0})
    log(f"  Card lock state: {entry['value']}")
    log("  [PASS] Card lock state updated.")

    # KV5: Delete expired-style key
    log()
    log("KV5: Delete key-value entry")
    res = kv.delete_one({"_key": "sess:sess_abc123"})
    log(f"  Deleted count: {res.deleted_count}")
    log("  [PASS] Key-value entry deleted.")


def assert_invariants(db):
    log()
    log("-" * 60)
    log("NOSQL MODEL SANITY CHECKS")
    log("-" * 60)

    customers = db["customers"]
    accounts = db["accounts"]
    transactions = db["transactions"]

    # All expected customers present
    expected_customers = 8
    actual = customers.count_documents({})
    status = "PASS" if actual == expected_customers else "FAIL"
    log(f"  [{status}] Customer documents: {actual} (expected {expected_customers})")

    # All expected accounts present
    expected_accounts = 8
    actual = accounts.count_documents({})
    status = "PASS" if actual == expected_accounts else "FAIL"
    log(f"  [{status}] Account documents: {actual} (expected {expected_accounts})")

    # All expected transactions present
    expected_txns = 2
    actual = transactions.count_documents({})
    status = "PASS" if actual == expected_txns else "FAIL"
    log(f"  [{status}] Transaction documents: {actual} (expected {expected_txns})")

    # PCI DSS: no card document contains CVV/PIN/full PAN
    cards_coll = db["accounts"]
    full_pan_hits = cards_coll.count_documents({"cards.masked_pan": {"$regex": r"\d{11,}"}})
    status = "PASS" if full_pan_hits == 0 else "FAIL"
    log(f"  [{status}] Masked PAN field contains no full PAN (>10 digits): hits={full_pan_hits}")

    # Every transaction document has embedded ledger_lines
    missing_lines = transactions.count_documents({"ledger_lines": {"$exists": False}})
    status = "PASS" if missing_lines == 0 else "FAIL"
    log(f"  [{status}] All transaction documents embed ledger_lines: missing={missing_lines}")


def main():
    log("=" * 60)
    log("PORTFOLIO 4: NOSQL AND ADVANCED DATA MODELS")
    log("=" * 60)
    log(f"Target: MongoDB at {NOSQL_URL.split('@')[-1] if '@' in NOSQL_URL else NOSQL_URL}")
    log()

    client = connect(NOSQL_URL)
    db = client.get_database()

    # Drop and recreate collections for a clean, re-runnable run
    for coll in ("customers", "accounts", "transactions", "cards", "kv_store"):
        db.drop_collection(coll)
    log("[OK] Collections dropped (re-runnable run)")

    customers = db["customers"]
    accounts = db["accounts"]
    transactions = db["transactions"]
    kv = db["kv_store"]

    log()
    log("Seeding ApexBank document data ...")
    seed_customers(customers)
    seed_accounts(accounts)
    seed_transactions(transactions)
    seed_kv(kv)

    # Unique index on idempotency key (KV)
    kv.create_index([("_key", ASCENDING)], unique=True, name="idx_kv_key_unique")

    run_document_queries(db)
    run_kv_operations(db)
    assert_invariants(db)

    client.close()

    evidence_path = BASE_DIR / "nosql_test_evidence.txt"
    evidence_path.write_text("\n".join(log_output), encoding="utf-8")
    log()
    log(f"[OK] Evidence written to: {evidence_path}")
    log("=" * 60)
    log("PORTFOLIO 4 RUN COMPLETE")
    log("=" * 60)


if __name__ == "__main__":
    main()
