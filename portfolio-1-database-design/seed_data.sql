-- ==============================================================================
-- MIT 8103 Advanced Database Systems - Practical Database Portfolio
-- Case Study: ApexBank Digital (Fintech & Core Banking Platform)
-- Portfolio 1: Seed Data Scripts (PostgreSQL 16)
-- ==============================================================================

-- 1. Currencies
INSERT INTO currencies (currency_code, currency_name, currency_symbol, decimal_places, is_active) VALUES
('USD', 'United States Dollar', '$', 2, TRUE),
('EUR', 'Euro', '€', 2, TRUE),
('GBP', 'British Pound Sterling', '£', 2, TRUE),
('NGN', 'Nigerian Naira', '₦', 2, TRUE);

-- 2. Account Types
INSERT INTO account_types (account_type_id, type_name, minimum_balance, interest_rate, default_overdraft_limit) VALUES
(1, 'Retail Tier 1 Savings', 0.0000, 0.0450, 0.0000),
(2, 'Retail Premier Checking', 50.0000, 0.0150, 1000.0000),
(3, 'SME Business High-Yield', 500.0000, 0.0350, 5000.0000),
(4, 'Institutional Settlement', 10000.0000, 0.0100, 50000.0000);

ALTER TABLE account_types ALTER COLUMN account_type_id RESTART WITH 5;

-- 3. Customers
INSERT INTO customers (customer_id, first_name, last_name, email, phone_number, password_hash, tier_level, status) VALUES
('c0000001-0000-4000-8000-000000000001', 'Amina', 'Bello', 'amina.bello@example.com', '+2348031112233', 'pbkdf2_sha256$600000$demo_salt_001$hash_001', 'TIER_3', 'ACTIVE'),
('c0000002-0000-4000-8000-000000000002', 'Chidi', 'Okonkwo', 'chidi.o@example.com', '+2348022223344', 'pbkdf2_sha256$600000$demo_salt_002$hash_002', 'TIER_3', 'ACTIVE'),
('c0000003-0000-4000-8000-000000000003', 'Folake', 'Adeyemi', 'folake.a@example.com', '+2348055556677', 'pbkdf2_sha256$600000$demo_salt_003$hash_003', 'TIER_2', 'ACTIVE'),
('c0000004-0000-4000-8000-000000000004', 'David', 'Kalu', 'david.kalu@example.com', '+2348109998877', 'pbkdf2_sha256$600000$demo_salt_004$hash_004', 'TIER_1', 'ACTIVE'),
('c0000005-0000-4000-8000-000000000005', 'Zainab', 'Mohammed', 'zainab.m@example.com', '+2348077778899', 'pbkdf2_sha256$600000$demo_salt_005$hash_005', 'TIER_3', 'ACTIVE'),
('c0000006-0000-4000-8000-000000000006', 'Kolawole', 'Balogun', 'kola.balogun@example.com', '+2348123456789', 'pbkdf2_sha256$600000$demo_salt_006$hash_006', 'TIER_3', 'ACTIVE'),
('c0000007-0000-4000-8000-000000000007', 'Ngozi', 'Eze', 'ngozi.eze@example.com', '+2348098765432', 'pbkdf2_sha256$600000$demo_salt_007$hash_007', 'TIER_2', 'ACTIVE'),
('c0000008-0000-4000-8000-000000000008', 'ApexBank', 'Internal Treasury', 'treasury@apexbank.internal', '+2348000000000', 'pbkdf2_sha256$600000$demo_salt_008$hash_008', 'TIER_3', 'ACTIVE');

-- 4. KYC Verifications
INSERT INTO kyc_verifications (kyc_id, customer_id, document_type, id_number, verification_status, verified_by, verified_at) VALUES
('d0000001-0000-4000-8000-000000000001', 'c0000001-0000-4000-8000-000000000001', 'NATIONAL_ID', 'NIN-1092837465', 'VERIFIED', 'system_aml_checker', '2026-01-15 09:30:00+01'),
('d0000002-0000-4000-8000-000000000002', 'c0000002-0000-4000-8000-000000000002', 'PASSPORT', 'A09876543', 'VERIFIED', 'officer_sarah_id44', '2026-02-10 11:15:00+01'),
('d0000003-0000-4000-8000-000000000003', 'c0000003-0000-4000-8000-000000000003', 'BVN', '22334455667', 'VERIFIED', 'system_aml_checker', '2026-03-01 14:00:00+01'),
('d0000004-0000-4000-8000-000000000004', 'c0000005-0000-4000-8000-000000000005', 'PASSPORT', 'B11223344', 'VERIFIED', 'officer_mike_id12', '2026-01-20 16:45:00+01'),
('d0000005-0000-4000-8000-000000000005', 'c0000006-0000-4000-8000-000000000006', 'NATIONAL_ID', 'NIN-8877665544', 'VERIFIED', 'officer_sarah_id44', '2026-02-18 10:00:00+01');

-- 5. Accounts
-- These are opening balances. Ledger postings below are applied by
-- trg_ledger_apply_balance, producing the final balances checked by the verifier.
INSERT INTO accounts (account_id, customer_id, account_type_id, currency_code, account_number, current_balance, hold_balance, overdraft_limit, version, account_status) VALUES
('a0000001-0000-4000-8000-000000000001', 'c0000001-0000-4000-8000-000000000001', 2, 'USD', '1000100101', 15003.0000, 0.0000, 1000.0000, 1, 'ACTIVE'),
('a0000002-0000-4000-8000-000000000002', 'c0000002-0000-4000-8000-000000000002', 2, 'USD', '1000100102', 7750.0000, 0.0000, 500.0000, 1, 'ACTIVE'),
('a0000003-0000-4000-8000-000000000003', 'c0000003-0000-4000-8000-000000000003', 1, 'NGN', '2000200201', 750000.0000, 0.0000, 0.0000, 1, 'ACTIVE'),
('a0000004-0000-4000-8000-000000000004', 'c0000004-0000-4000-8000-000000000004', 1, 'NGN', '2000200202', 45000.0000, 0.0000, 0.0000, 1, 'ACTIVE'),
('a0000005-0000-4000-8000-000000000005', 'c0000005-0000-4000-8000-000000000005', 2, 'USD', '1000100105', 32120.7500, 500.0000, 2000.0000, 1, 'ACTIVE'),
('a0000006-0000-4000-8000-000000000006', 'c0000006-0000-4000-8000-000000000006', 3, 'USD', '1000100106', 125281.8000, 0.0000, 5000.0000, 1, 'ACTIVE'),
('a0000007-0000-4000-8000-000000000007', 'c0000007-0000-4000-8000-000000000007', 1, 'USD', '1000100107', 3200.0000, 0.0000, 0.0000, 1, 'ACTIVE'),
('a0000008-0000-4000-8000-000000000008', 'c0000008-0000-4000-8000-000000000008', 4, 'USD', '9999000001', 18447.7500, 0.0000, 0.0000, 1, 'ACTIVE');

-- 6. Merchants
INSERT INTO merchants (merchant_id, settlement_account_id, business_name, registration_number, merchant_category_code, commission_rate, status) VALUES
('e0000001-0000-4000-8000-000000000001', 'a0000006-0000-4000-8000-000000000006', 'Apex Superstores Ltd', 'RC-99887766', '5411', 0.0150, 'ACTIVE');

-- 7. Cards (tokenised; no CVV and no PIN are stored)
INSERT INTO cards (card_id, account_id, masked_pan, card_token, pan_hmac, expiry_date, card_type, daily_spend_limit, card_status) VALUES
('f0000001-0000-4000-8000-000000000001', 'a0000001-0000-4000-8000-000000000001', '411111XXXXXX1122', 'tok_vault_6b1f0c2a9d4e8f7b', '2cd4bde77ae262c960a8643c57c18048bcad51885f144496dd51ae36cb0b8169', '2028-12-31', 'DEBIT', 5000.0000, 'ACTIVE'),
('f0000002-0000-4000-8000-000000000002', 'a0000002-0000-4000-8000-000000000002', '422222XXXXXX3344', 'tok_vault_7c2a1d3b0e5f9a8c', '00ff9f8f47d61bdc53831307ec68dd966495b9d8271c87e4173f56d7c81a6756', '2027-08-31', 'DEBIT', 3000.0000, 'ACTIVE'),
('f0000003-0000-4000-8000-000000000003', 'a0000005-0000-4000-8000-000000000005', '433333XXXXXX5566', 'tok_vault_8d3b2e4c1f6a0b9d', 'ed734670251bfc2e49b6d00cfc02c56a9de673de5edd3110afbc43d3e0eb5c0f', '2029-05-31', 'VIRTUAL_DEBIT', 10000.0000, 'ACTIVE');

-- 8. Journal Entries (Double-Entry Headers)
INSERT INTO journal_entries (journal_id, entry_reference, narrative, event_type, posting_date, created_at) VALUES
('10000001-0000-4000-8000-000000000001', 'JRN-2026-10-001', 'P2P Transfer Amina -> Chidi', 'P2P_TRANSFER', '2026-10-25 10:14:00+01', '2026-10-25 10:14:00+01'),
('10000002-0000-4000-8000-000000000002', 'JRN-2026-10-002', 'Card Payment at Apex Superstores by Zainab', 'CARD_PAYMENT', '2026-10-26 14:30:00+01', '2026-10-26 14:30:00+01');

-- 9. Ledger Entries
-- Journal 1: Debit Amina $502.50 = Credit Chidi $500.00 + Credit Bank Fees $2.50
-- Journal 2: Debit Zainab $120.00 = Credit Merchant $118.20 + Credit Bank Fees $1.80
INSERT INTO ledger_entries (ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after, created_at) VALUES
('20000001-0000-4000-8000-000000000001', '10000001-0000-4000-8000-000000000001', 'a0000001-0000-4000-8000-000000000001', 'DEBIT', 502.5000, 14500.5000, '2026-10-25 10:14:00+01'),
('20000002-0000-4000-8000-000000000002', '10000001-0000-4000-8000-000000000001', 'a0000002-0000-4000-8000-000000000002', 'CREDIT', 500.0000, 8250.0000, '2026-10-25 10:14:00+01'),
('20000003-0000-4000-8000-000000000003', '10000001-0000-4000-8000-000000000001', 'a0000008-0000-4000-8000-000000000008', 'CREDIT', 2.5000, 18450.2500, '2026-10-25 10:14:00+01'),
('20000004-0000-4000-8000-000000000004', '10000002-0000-4000-8000-000000000002', 'a0000005-0000-4000-8000-000000000005', 'DEBIT', 120.0000, 32000.7500, '2026-10-26 14:30:00+01'),
('20000005-0000-4000-8000-000000000005', '10000002-0000-4000-8000-000000000002', 'a0000006-0000-4000-8000-000000000006', 'CREDIT', 118.2000, 125400.0000, '2026-10-26 14:30:00+01'),
('20000006-0000-4000-8000-000000000006', '10000002-0000-4000-8000-000000000002', 'a0000008-0000-4000-8000-000000000008', 'CREDIT', 1.8000, 18452.0500, '2026-10-26 14:30:00+01');

-- 10. Transactions
INSERT INTO transactions (transaction_id, transaction_reference, idempotency_key, source_account_id, destination_account_id, merchant_id, journal_id, currency_code, amount, fee_amount, channel, status, initiated_at, completed_at) VALUES
('30000001-0000-4000-8000-000000000001', 'TXN-20261025-001', 'idem-key-889911-a', 'a0000001-0000-4000-8000-000000000001', 'a0000002-0000-4000-8000-000000000002', NULL, '10000001-0000-4000-8000-000000000001', 'USD', 500.0000, 2.5000, 'MOBILE_APP', 'SETTLED', '2026-10-25 10:13:58+01', '2026-10-25 10:14:01+01'),
('30000002-0000-4000-8000-000000000002', 'TXN-20261026-002', 'idem-key-991122-b', 'a0000005-0000-4000-8000-000000000005', 'a0000006-0000-4000-8000-000000000006', 'e0000001-0000-4000-8000-000000000001', '10000002-0000-4000-8000-000000000002', 'USD', 120.0000, 1.8000, 'POS_TERMINAL', 'SETTLED', '2026-10-26 14:29:55+01', '2026-10-26 14:30:02+01');

-- 11. Audit Logs
INSERT INTO audit_logs (audit_id, customer_id, actor_reference, action, target_table, target_record_id, old_values, new_values, ip_address, created_at) VALUES
('40000001-0000-4000-8000-000000000001', 'c0000001-0000-4000-8000-000000000001', 'customer:c0000001-0000-4000-8000-000000000001', 'CUSTOMER_LOGIN', 'customers', 'c0000001-0000-4000-8000-000000000001', NULL, '{"login_method": "biometric", "device": "iPhone15"}'::jsonb, '197.210.65.12', '2026-10-25 10:10:00+01'),
('40000002-0000-4000-8000-000000000002', 'c0000001-0000-4000-8000-000000000001', 'customer:c0000001-0000-4000-8000-000000000001', 'TRANSFER_INITIATION', 'transactions', '30000001-0000-4000-8000-000000000001', NULL, '{"amount": 500.00, "destination_account_id": "a0000002-0000-4000-8000-000000000002"}'::jsonb, '197.210.65.12', '2026-10-25 10:13:58+01');
