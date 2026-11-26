-- =====================================================================================
-- 02  Star schema in Redshift
--
--   fct_wallet_monthly  (wallet x month)          DISTKEY(wallet)  SORTKEY(activity_month)
--   fct_wallet_daily    (wallet x day)            DISTKEY(wallet)  SORTKEY(activity_date)
--   fct_transfers_daily (date x token x bucket..) DISTSTYLE ALL    SORTKEY(activity_date)
--   fct_network_hourly  (hour)                    DISTSTYLE ALL    SORTKEY(hour_ts)
--   dim_wallet (SCD2)                             DISTKEY(wallet)  SORTKEY(wallet, valid_from)
--   dim_token, dim_ticket_bucket, dim_date        DISTSTYLE ALL
--
-- Why: the two big tables and dim_wallet share DISTKEY(wallet), so wallet-level joins
-- (as-of SCD2 lookups, cohort building) are co-located on the same slice with no
-- redistribution. Everything else is small enough to copy to every node (ALL).
-- Facts are sorted by their date so dashboard date filters skip blocks via zone maps.
-- Wallet addresses are fixed-width hex: CHAR(42) with ZSTD.
-- =====================================================================================

CREATE TABLE IF NOT EXISTS core.dim_date (
    date_day      DATE NOT NULL PRIMARY KEY,
    week_start    DATE,
    month_start   DATE,
    year_number   SMALLINT,
    day_of_week   SMALLINT,
    is_weekend    BOOLEAN,
    protocol_era  VARCHAR(16)
) DISTSTYLE ALL SORTKEY (date_day);

CREATE TABLE IF NOT EXISTS core.dim_token (
    token_key             CHAR(32)    NOT NULL PRIMARY KEY,
    token_address         CHAR(42)    NOT NULL,
    token_symbol          VARCHAR(8)  NOT NULL,
    issuer                VARCHAR(64),
    decimals              SMALLINT,
    peg                   CHAR(3),
    launched_on_ethereum  DATE
) DISTSTYLE ALL;

CREATE TABLE IF NOT EXISTS core.dim_ticket_bucket (
    ticket_bucket    VARCHAR(16) NOT NULL PRIMARY KEY,
    label            VARCHAR(32),
    lower_usd        DECIMAL(18,2),
    upper_usd        DECIMAL(18,2),
    is_small_ticket  BOOLEAN,
    sort_order       SMALLINT
) DISTSTYLE ALL;

CREATE TABLE IF NOT EXISTS core.dim_wallet (
    wallet_key          CHAR(32)    NOT NULL PRIMARY KEY ENCODE ZSTD,
    wallet              CHAR(42)    NOT NULL ENCODE ZSTD,
    segment             VARCHAR(32) ENCODE BYTEDICT,
    version_no          SMALLINT,
    months_in_version   SMALLINT,
    valid_from          DATE        NOT NULL,
    valid_to            DATE        NOT NULL DEFAULT '9999-12-31',
    is_current          BOOLEAN,
    first_seen_date     DATE,
    first_receive_date  DATE,
    first_send_date     DATE,
    primary_token       VARCHAR(8)  ENCODE BYTEDICT,
    is_new_in_window    BOOLEAN
) DISTKEY (wallet) COMPOUND SORTKEY (wallet, valid_from);

CREATE TABLE IF NOT EXISTS core.fct_wallet_monthly (
    wallet_month_key         CHAR(32) NOT NULL PRIMARY KEY ENCODE ZSTD,
    wallet_key               CHAR(32) REFERENCES core.dim_wallet (wallet_key) ENCODE ZSTD,
    wallet                   CHAR(42) NOT NULL ENCODE ZSTD,
    activity_month           DATE     NOT NULL,
    months_since_first_seen  SMALLINT,
    segment                  VARCHAR(32) ENCODE BYTEDICT,
    active_days              SMALLINT,
    sent_n                   INTEGER  ENCODE AZ64,
    sent_usd                 DOUBLE PRECISION,
    recv_n                   INTEGER  ENCODE AZ64,
    recv_usd                 DOUBLE PRECISION,
    sent_small_n             INTEGER  ENCODE AZ64,
    to_contract_share        REAL,
    avg_ticket_sent          DOUBLE PRECISION,
    counterparties_out       INTEGER,
    counterparties_in        INTEGER,
    usdc_n                   INTEGER,
    usdt_n                   INTEGER
) DISTKEY (wallet) COMPOUND SORTKEY (activity_month, segment);

CREATE TABLE IF NOT EXISTS core.fct_wallet_daily (
    wallet              CHAR(42) NOT NULL ENCODE ZSTD,
    activity_date       DATE     NOT NULL,
    sent_n              INTEGER  ENCODE AZ64,
    sent_usd            DOUBLE PRECISION,
    recv_n              INTEGER  ENCODE AZ64,
    recv_usd            DOUBLE PRECISION,
    sent_small_n        INTEGER  ENCODE AZ64,
    sent_to_contract_n  INTEGER  ENCODE AZ64,
    counterparties_out  INTEGER,
    counterparties_in   INTEGER,
    usdc_n              INTEGER,
    usdt_n              INTEGER,
    dai_n               INTEGER,
    pyusd_n             INTEGER,
    max_sent_usd        DOUBLE PRECISION
) DISTKEY (wallet) COMPOUND SORTKEY (activity_date);

CREATE TABLE IF NOT EXISTS core.fct_transfers_daily (
    activity_date      DATE NOT NULL,
    token_key          CHAR(32) REFERENCES core.dim_token (token_key),
    token_symbol       VARCHAR(8),
    ticket_bucket      VARCHAR(16) REFERENCES core.dim_ticket_bucket (ticket_bucket),
    transfer_kind      VARCHAR(8),
    flow_type          VARCHAR(24),
    flow_category      VARCHAR(24),
    transfers          BIGINT,
    volume_usd         DOUBLE PRECISION,
    senders_approx     BIGINT,
    receivers_approx   BIGINT,
    avg_base_fee_gwei  DOUBLE PRECISION,
    median_fee_usd     DOUBLE PRECISION,
    median_amount_usd  DOUBLE PRECISION
) DISTSTYLE ALL COMPOUND SORTKEY (activity_date, token_symbol);

CREATE TABLE IF NOT EXISTS core.fct_network_hourly (
    hour_ts                TIMESTAMP NOT NULL PRIMARY KEY,
    activity_date          DATE,
    hour_of_day            SMALLINT,
    day_of_week            SMALLINT,
    protocol_era           VARCHAR(16),
    avg_base_fee_gwei      DOUBLE PRECISION,
    avg_block_utilization  DOUBLE PRECISION,
    network_tx_count       BIGINT,
    blocks                 INTEGER,
    eth_usd                DOUBLE PRECISION,
    oracle_swaps           INTEGER,
    est_transfer_fee_usd   DOUBLE PRECISION
) DISTSTYLE ALL SORTKEY (hour_ts);
