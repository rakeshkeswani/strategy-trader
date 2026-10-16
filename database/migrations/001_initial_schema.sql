-- 001_initial_schema.sql -- ST-012 (2026-10-15): the 14 tables of the approved data model (docs/DATA_MODEL.md s.4).
-- Applied by `python -m scripts.migrate` as stratrad_app (owner), inside one transaction.
-- Conventions: timestamptz (sessions run in UTC; shown in IST); money numeric(14,2) INR; prices numeric(12,2);
-- quantities integer; every table has id bigserial and created_at; status changes are rows in order_events;
-- raw broker payloads jsonb (kept indefinitely). Exceptions, on purpose: Kite's average fill price and per-order
-- charge components keep 4 decimals (Kite reports them finer than paisa); adjustment factors keep 8.

-- ---- strategies and models ---------------------------------------------------------------------------------------
CREATE TABLE strategies (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,
    version     integer NOT NULL CHECK (version >= 1),
    config      jsonb NOT NULL DEFAULT '{}'::jsonb,
    status      text NOT NULL CHECK (status IN ('draft', 'approved', 'live', 'paused', 'retired')),
    approved_by text,
    approved_at timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version),
    CHECK (status NOT IN ('approved', 'live') OR approved_at IS NOT NULL)
);

CREATE TABLE models (
    id            bigserial PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('regime', 'allocator', 'ranker')),
    version       text NOT NULL,
    artifact_path text NOT NULL,
    metrics       jsonb NOT NULL DEFAULT '{}'::jsonb,
    gate          text NOT NULL DEFAULT 'pending' CHECK (gate IN ('pending', 'passed', 'failed')),
    approved_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (kind, version)
);

-- ---- entry path: signals -> proposals ----------------------------------------------------------------------------
CREATE TABLE signals (
    id          bigserial PRIMARY KEY,
    run_date    date NOT NULL,
    strategy_id bigint NOT NULL REFERENCES strategies (id),
    model_id    bigint REFERENCES models (id),
    symbol      text NOT NULL,
    isin        text,
    sector      text,
    score       numeric(18, 8),
    rank        integer CHECK (rank >= 1),
    rationale   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_date, strategy_id, symbol)
);
CREATE INDEX signals_run_date ON signals (run_date);

CREATE TABLE proposals (
    id                  bigserial PRIMARY KEY,
    signal_id           bigint NOT NULL REFERENCES signals (id),
    symbol              text NOT NULL,
    sector              text,
    qty                 integer NOT NULL CHECK (qty > 0),
    limit_price         numeric(12, 2) NOT NULL CHECK (limit_price > 0),
    stop_price          numeric(12, 2) CHECK (stop_price > 0),
    amount              numeric(14, 2) NOT NULL CHECK (amount > 0),
    status              text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'blocked')),
    decided_at          timestamptz,
    telegram_chat_id    bigint,
    telegram_message_id bigint,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (status = 'pending' OR decided_at IS NOT NULL)
);
CREATE INDEX proposals_status ON proposals (status);

-- ---- lots, orders, stops -----------------------------------------------------------------------------------------
CREATE TABLE positions (
    id               bigserial PRIMARY KEY,
    strategy_id      bigint NOT NULL REFERENCES strategies (id),
    symbol           text NOT NULL,
    isin             text,
    instrument_token bigint,
    sector           text,
    entry_date       date NOT NULL,
    entry_price      numeric(12, 2) NOT NULL CHECK (entry_price > 0),
    entry_qty        integer NOT NULL CHECK (entry_qty > 0),
    exit_date        date,
    exit_price       numeric(12, 2) CHECK (exit_price > 0),
    exit_qty         integer CHECK (exit_qty > 0),
    exit_reason      text CHECK (exit_reason IN ('stop', 'trail', 'manual', 'rule')),
    status           text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    realised_pnl     numeric(14, 2),
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'open' AND exit_date IS NULL AND exit_price IS NULL AND exit_qty IS NULL AND exit_reason IS NULL)
        OR (status = 'closed' AND exit_date IS NOT NULL AND exit_price IS NOT NULL AND exit_qty IS NOT NULL
            AND exit_reason IS NOT NULL AND exit_date >= entry_date))
);
CREATE INDEX positions_open ON positions (symbol) WHERE status = 'open';
CREATE INDEX positions_strategy ON positions (strategy_id, status);

CREATE TABLE orders (
    id               bigserial PRIMARY KEY,
    proposal_id      bigint REFERENCES proposals (id),
    position_id      bigint REFERENCES positions (id),
    kite_order_id    text UNIQUE,
    symbol           text NOT NULL,
    instrument_token bigint,
    side             text NOT NULL CHECK (side IN ('BUY', 'SELL')),
    qty              integer NOT NULL CHECK (qty > 0),
    price            numeric(12, 2) CHECK (price > 0),
    order_type       text NOT NULL CHECK (order_type IN ('LIMIT', 'MARKET', 'SL', 'SL-M')),
    reason           text NOT NULL CHECK (reason IN ('entry', 'stop', 'manual', 'exit')),
    status           text NOT NULL,
    filled_qty       integer NOT NULL DEFAULT 0 CHECK (filled_qty >= 0 AND filled_qty <= qty),
    avg_price        numeric(12, 4) CHECK (avg_price > 0),
    raw              jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(proposal_id, position_id) >= 1)
);
CREATE INDEX orders_position ON orders (position_id);
CREATE INDEX orders_proposal ON orders (proposal_id);

CREATE TABLE order_charges (
    id            bigserial PRIMARY KEY,
    order_id      bigint NOT NULL REFERENCES orders (id),
    brokerage     numeric(14, 4) NOT NULL DEFAULT 0,
    stt           numeric(14, 4) NOT NULL DEFAULT 0,
    exchange_txn  numeric(14, 4) NOT NULL DEFAULT 0,
    sebi          numeric(14, 4) NOT NULL DEFAULT 0,
    stamp_duty    numeric(14, 4) NOT NULL DEFAULT 0,
    gst           numeric(14, 4) NOT NULL DEFAULT 0,
    total         numeric(14, 4) NOT NULL,
    source        text NOT NULL CHECK (source IN ('virtual_contract_note', 'contract_note')),
    reconciled_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (order_id, source)
);

CREATE TABLE gtt_orders (
    id            bigserial PRIMARY KEY,
    position_id   bigint NOT NULL REFERENCES positions (id),
    kite_gtt_id   bigint UNIQUE,
    trigger_price numeric(12, 2) NOT NULL CHECK (trigger_price > 0),
    limit_price   numeric(12, 2) NOT NULL CHECK (limit_price > 0),
    status        text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX gtt_orders_position ON gtt_orders (position_id);

CREATE TABLE position_adjustments (
    id                 bigserial PRIMARY KEY,
    position_id        bigint NOT NULL REFERENCES positions (id),
    ex_date            date NOT NULL,
    action_type        text NOT NULL CHECK (action_type IN ('split', 'bonus', 'demerger', 'other')),
    factor             numeric(18, 8) NOT NULL CHECK (factor > 0),
    qty_before         integer NOT NULL,
    qty_after          integer NOT NULL,
    entry_price_before numeric(12, 4) NOT NULL,
    entry_price_after  numeric(12, 4) NOT NULL,
    stop_before        numeric(12, 2),
    stop_after         numeric(12, 2),
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (position_id, ex_date, action_type)
);

-- ---- events, guardrails, daily state, reconciliation, audit ------------------------------------------------------
CREATE TABLE order_events (
    id          bigserial PRIMARY KEY,
    order_id    bigint REFERENCES orders (id),
    gtt_id      bigint REFERENCES gtt_orders (id),
    proposal_id bigint REFERENCES proposals (id),
    from_status text,
    to_status   text NOT NULL,
    at          timestamptz NOT NULL DEFAULT now(),
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(order_id, gtt_id, proposal_id) = 1)
);
CREATE INDEX order_events_order ON order_events (order_id);
CREATE INDEX order_events_gtt ON order_events (gtt_id);
CREATE INDEX order_events_proposal ON order_events (proposal_id);

CREATE TABLE guardrail_events (
    id          bigserial PRIMARY KEY,
    stage       text NOT NULL CHECK (stage IN ('before_proposal', 'before_order')),
    rule        text NOT NULL,
    decision    text NOT NULL CHECK (decision IN ('allow', 'block')),
    proposal_id bigint REFERENCES proposals (id),
    limits      jsonb NOT NULL DEFAULT '{}'::jsonb,
    context     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX guardrail_events_created ON guardrail_events (created_at);

CREATE TABLE daily_snapshots (
    id                   bigserial PRIMARY KEY,
    snapshot_date        date NOT NULL UNIQUE,
    invested_at_cost     numeric(14, 2) NOT NULL,
    market_value         numeric(14, 2) NOT NULL,
    realised_pnl         numeric(14, 2) NOT NULL,
    unrealised_pnl       numeric(14, 2) NOT NULL,
    loss_12m_pct         numeric(8, 4),
    tier                 text NOT NULL CHECK (tier IN ('ok', 'alert', 'no_buys', 'halt')),
    exposure_by_strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
    exposure_by_sector   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reconciliations (
    id          bigserial PRIMARY KEY,
    recon_date  date NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('holdings', 'gtt', 'charges')),
    symbol      text,
    expected    jsonb,
    actual      jsonb,
    difference  jsonb,
    resolved_at timestamptz,
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reconciliations_open ON reconciliations (recon_date) WHERE resolved_at IS NULL;

CREATE TABLE audit_log (
    id         bigserial PRIMARY KEY,
    actor      text NOT NULL CHECK (actor IN ('system', 'rakesh')),
    action     text NOT NULL,
    details    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- audit_log is append-only for everyone, the owner included (a trigger, not a grant, because owners bypass grants).
CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only (% refused)', TG_OP;
END;
$$;
CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();

-- ---- seed and read access ----------------------------------------------------------------------------------------
-- Rakesh's own holdings are lots of strategy 'manual' (docs/DATA_MODEL.md s.4, 2026-10-14).
INSERT INTO strategies (name, version, config, status, approved_by, approved_at)
VALUES ('manual', 1, '{"note": "Rakesh''s own holdings and trades, imported from Kite"}', 'live', 'rakesh', now());

GRANT USAGE ON SCHEMA public TO stratrad_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO stratrad_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO stratrad_reader;
