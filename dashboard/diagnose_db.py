"""Read-only Neon dashboard diagnostic.

Run locally with the same DATABASE_URL value used by the dashboard:
    DATABASE_URL='...' python dashboard/diagnose_db.py

This script performs SELECTs only. It does not alter data or schema.
"""
import os
from datetime import timezone, timedelta
from urllib.parse import urlparse

import psycopg

IST = timezone(timedelta(hours=5, minutes=30))

# Verified through Neon control-plane endpoint metadata on 2026-11-18.
# Unknown endpoint IDs are deliberately reported as unmapped.
VERIFIED_ENDPOINT_BRANCHES = {
    "ep-sparkling-queen-aoqgp0mw": "br-lingering-grass-ao07mgrx",
}


def endpoint_id_from_url(database_url: str) -> str:
    host = urlparse(database_url).hostname or ""
    endpoint = host.split(".", 1)[0]
    return endpoint.removesuffix("-pooler")


def fmt_ist(value) -> str:
    if value is None:
        return "—"
    return value.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("ERROR: DATABASE_URL environment variable is not set.")

    endpoint_id = endpoint_id_from_url(database_url)
    branch_id = VERIFIED_ENDPOINT_BRANCHES.get(endpoint_id)

    # Use a read-only transaction even if the database role permits writes.
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(
                """
                WITH bounds AS (
                    SELECT
                        date_trunc('day', now() AT TIME ZONE 'UTC')
                            AT TIME ZONE 'UTC' AS session_start,
                        now() AS checked_at
                ),
                candles AS (
                    SELECT series_type, candle_time
                    FROM research.delta_candles, bounds
                    WHERE source = 'delta_india'
                      AND resolution = '30m'
                      AND (
                        (series_type = 'PRICE' AND symbol = 'BTCUSD')
                        OR
                        (series_type = 'OI' AND symbol = 'OI:BTCUSD')
                      )
                      AND candle_time >= bounds.session_start
                      AND candle_time < bounds.checked_at
                )
                SELECT
                    current_database() AS database_name,
                    current_user AS role_name,
                    inet_server_addr()::text AS server_address,
                    (SELECT session_start FROM bounds) AS session_start_utc,
                    (SELECT checked_at FROM bounds) AS checked_at_utc,
                    count(*) FILTER (WHERE series_type = 'PRICE') AS price_count,
                    max(candle_time) FILTER (WHERE series_type = 'PRICE')
                        AS latest_price_utc,
                    count(*) FILTER (WHERE series_type = 'OI') AS oi_count,
                    max(candle_time) FILTER (WHERE series_type = 'OI')
                        AS latest_oi_utc,
                    count(DISTINCT candle_time) FILTER (
                        WHERE series_type = 'PRICE'
                    ) AS distinct_price_slots,
                    count(DISTINCT candle_time) FILTER (
                        WHERE series_type = 'OI'
                    ) AS distinct_oi_slots,
                    count(DISTINCT candle_time) AS total_distinct_slots,
                    count(DISTINCT candle_time) FILTER (
                        WHERE candle_time IN (
                            SELECT p.candle_time FROM candles p
                            WHERE p.series_type = 'PRICE'
                            INTERSECT
                            SELECT o.candle_time FROM candles o
                            WHERE o.series_type = 'OI'
                        )
                    ) AS paired_confirmed_slots
                FROM candles
                """
            )
            row = cur.fetchone()
            conn.commit()

    (
        database_name, role_name, server_address, session_start, checked_at,
        price_count, latest_price, oi_count, latest_oi,
        distinct_price, distinct_oi, total_slots, paired_slots,
    ) = row

    print("\nREAD-ONLY NEON DASHBOARD DIAGNOSTIC")
    print("=" * 42)
    print(f"Endpoint ID:             {endpoint_id}")
    print(f"Branch ID (verified map): {branch_id or 'UNMAPPED — verify in Neon console'}")
    print(f"Database:                {database_name}")
    print(f"Role:                    {role_name}")
    print(f"Server address:          {server_address or 'not exposed'}")
    print(f"Session start:           {fmt_ist(session_start)}")
    print(f"Checked at:              {fmt_ist(checked_at)}")
    print("-" * 42)
    print(f"Confirmed PRICE candles: {price_count}")
    print(f"Latest PRICE candle:     {fmt_ist(latest_price)}")
    print(f"Confirmed OI candles:    {oi_count}")
    print(f"Latest OI candle:        {fmt_ist(latest_oi)}")
    print(f"Distinct PRICE slots:    {distinct_price}")
    print(f"Distinct OI slots:       {distinct_oi}")
    print(f"Distinct session slots:  {total_slots}")
    print(f"Paired PRICE/OI slots:    {paired_slots}")
    print("\nNote: rows in research.delta_candles are confirmed history;")
    print("provisional candles are stored separately and are not counted.")
    print("Branch ID is shown only when the endpoint is in the verified map.\n")


if __name__ == "__main__":
    main()
