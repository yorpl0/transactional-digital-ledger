CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    balance numeric(20,2) NOT NULL DEFAULT 0,
    is_system boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX one_system_account_per_currency ON accounts(currency) WHERE is_system;

CREATE TABLE journal_entries (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('opening', 'transfer')),
    reference text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE postings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    journal_entry_id bigint NOT NULL REFERENCES journal_entries(id),
    account_id uuid NOT NULL REFERENCES accounts(id),
    amount numeric(20,2) NOT NULL CHECK (amount <> 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (journal_entry_id, account_id)
);

CREATE TABLE transfers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_entry_id bigint NOT NULL UNIQUE REFERENCES journal_entries(id),
    from_account_id uuid NOT NULL REFERENCES accounts(id),
    to_account_id uuid NOT NULL REFERENCES accounts(id),
    amount numeric(20,2) NOT NULL CHECK (amount > 0),
    currency char(3) NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (from_account_id <> to_account_id)
);

CREATE TABLE idempotency_keys (
    key text PRIMARY KEY,
    request_hash char(64) NOT NULL,
    response jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION reject_posting_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'postings are immutable';
END $$;

CREATE TRIGGER postings_no_update_or_delete
BEFORE UPDATE OR DELETE ON postings
FOR EACH ROW EXECUTE FUNCTION reject_posting_mutation();

CREATE TRIGGER journal_no_update_or_delete
BEFORE UPDATE OR DELETE ON journal_entries
FOR EACH ROW EXECUTE FUNCTION reject_posting_mutation();

CREATE FUNCTION enforce_balanced_journal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT COALESCE(SUM(amount), 0) FROM postings
        WHERE journal_entry_id = NEW.journal_entry_id) <> 0 THEN
        RAISE EXCEPTION 'journal entry % is not balanced', NEW.journal_entry_id;
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER journal_must_balance
AFTER INSERT ON postings DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_balanced_journal();

CREATE FUNCTION enforce_journal_has_balanced_postings() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM postings WHERE journal_entry_id = NEW.id)
       OR (SELECT SUM(amount) FROM postings WHERE journal_entry_id = NEW.id) <> 0 THEN
        RAISE EXCEPTION 'journal entry % must have balanced postings', NEW.id;
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER journal_requires_postings
AFTER INSERT ON journal_entries DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_journal_has_balanced_postings();

INSERT INTO accounts(name, currency, balance, is_system) VALUES
    ('Opening equity (USD)', 'USD', 0, true),
    ('Opening equity (EUR)', 'EUR', 0, true),
    ('Opening equity (INR)', 'INR', 0, true);
