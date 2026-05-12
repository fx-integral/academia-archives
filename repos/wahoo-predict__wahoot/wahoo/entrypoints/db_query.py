import argparse
import sqlite3
import sys
from typing import Optional

from wahoo.validator.database.validator_db import get_db_path


def connect_db():
    """Connect to the validator database."""
    db_path = get_db_path()
    if not db_path.exists():
        print(f"❌ Database not found at: {db_path}")
        print("   Run the validator first to create the database.")
        sys.exit(1)
    return sqlite3.connect(str(db_path))


def show_stats():
    """Show database statistics."""
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM miners")
    miner_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM scoring_runs")
    score_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM performance_snapshots")
    perf_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM validation_cache")
    cache_count = cursor.fetchone()[0]

    cursor.execute("SELECT MAX(ts) FROM scoring_runs")
    latest_score = cursor.fetchone()[0]

    cursor.execute("SELECT MAX(timestamp) FROM performance_snapshots")
    latest_perf = cursor.fetchone()[0]

    conn.close()

    print("\n📊 Database Statistics:")
    print("=" * 60)
    print(f"Registered Miners:     {miner_count}")
    print(f"Total Score Runs:       {score_count}")
    print(f"Performance Snapshots:  {perf_count}")
    print(f"Cached Validations:    {cache_count}")
    print(f"Latest Score:          {latest_score[:19] if latest_score else 'N/A'}")
    print(f"Latest Performance:    {latest_perf[:19] if latest_perf else 'N/A'}")
    print(f"Database Path:         {get_db_path()}")


def list_miners():
    """List all registered miners."""
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT hotkey, uid, last_seen_ts, first_seen_ts, axon_ip
        FROM miners
        ORDER BY uid NULLS LAST, hotkey
    """
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No miners found in database.")
        return

    print(f"\n📊 Registered Miners ({len(rows)} total):")
    print("=" * 100)
    print(
        f"{'Hotkey':<50} {'UID':<6} {'First Seen':<20} {'Last Seen':<20} {'Axon IP':<15}"
    )
    print("-" * 100)
    for hotkey, uid, last_seen, first_seen, axon_ip in rows:
        uid_str = str(uid) if uid else "N/A"
        first_seen_str = first_seen[:19] if first_seen else "N/A"
        last_seen_str = last_seen[:19] if last_seen else "N/A"
        axon_ip_str = axon_ip or "N/A"
        print(
            f"{hotkey:<50} {uid_str:<6} {first_seen_str:<20} {last_seen_str:<20} {axon_ip_str:<15}"
        )


def show_scores(limit: int = 20):
    """Show latest EMA scores."""
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sr.ts, sr.hotkey, sr.score, sr.reason, m.uid
        FROM scoring_runs sr
        LEFT JOIN miners m ON sr.hotkey = m.hotkey
        ORDER BY sr.ts DESC
        LIMIT ?
    """,
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No scores found in database.")
        return

    print(f"\n📈 Latest EMA Scores (showing {len(rows)} most recent):")
    print("=" * 120)
    print(f"{'Timestamp':<20} {'Hotkey':<50} {'UID':<6} {'Score':<12} {'Reason':<20}")
    print("-" * 120)
    for ts, hotkey, score, reason, uid in rows:
        ts_str = ts[:19] if ts else "N/A"
        uid_str = str(uid) if uid else "N/A"
        score_str = f"{score:.6f}" if score is not None else "N/A"
        reason_str = (
            (reason[:17] + "...") if reason and len(reason) > 20 else (reason or "")
        )
        print(
            f"{ts_str:<20} {hotkey:<50} {uid_str:<6} {score_str:<12} {reason_str:<20}"
        )


def show_latest_scores():
    """Show latest score for each miner."""
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sr.hotkey, sr.score, sr.ts, m.uid
        FROM scoring_runs sr
        INNER JOIN (
            SELECT hotkey, MAX(ts) as max_ts
            FROM scoring_runs
            GROUP BY hotkey
        ) latest ON sr.hotkey = latest.hotkey AND sr.ts = latest.max_ts
        LEFT JOIN miners m ON sr.hotkey = m.hotkey
        ORDER BY sr.score DESC NULLS LAST
    """
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No scores found in database.")
        return

    print(f"\n📊 Latest EMA Score for Each Miner ({len(rows)} miners):")
    print("=" * 100)
    print(f"{'Hotkey':<50} {'UID':<6} {'Score':<15} {'Timestamp':<20}")
    print("-" * 100)
    for hotkey, score, ts, uid in rows:
        uid_str = str(uid) if uid else "N/A"
        score_str = f"{score:.6f}" if score else "N/A"
        ts_str = ts[:19] if ts else "N/A"
        print(f"{hotkey:<50} {uid_str:<6} {score_str:<15} {ts_str:<20}")


def show_performance(hotkey: Optional[str] = None, limit: int = 10):
    """Show performance snapshots."""
    conn = connect_db()
    cursor = conn.cursor()

    if hotkey:
        cursor.execute(
            """
            SELECT timestamp, hotkey, weighted_volume, trade_count,
                   realized_profit_usd, win_rate, activity_score
            FROM performance_snapshots
            WHERE hotkey = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (hotkey, limit),
        )
    else:
        cursor.execute(
            """
            SELECT timestamp, hotkey, weighted_volume, trade_count,
                   realized_profit_usd, win_rate, activity_score
            FROM performance_snapshots
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (limit,),
        )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No performance data found.")
        return

    print(f"\n💹 Performance Snapshots (showing {len(rows)} most recent):")
    print("=" * 140)
    print(
        f"{'Timestamp':<20} {'Hotkey':<50} {'Volume USD':<15} {'Trades':<8} {'Profit USD':<15} {'Win Rate':<10} {'Activity':<10}"
    )
    print("-" * 140)
    for ts, hk, volume, trades, profit, win_rate, activity in rows:
        ts_str = ts[:19] if ts else "N/A"
        volume_str = f"${volume:,.2f}" if volume else "N/A"
        trades_str = str(trades) if trades else "0"
        profit_str = f"${profit:,.2f}" if profit else "N/A"
        win_rate_str = f"{win_rate*100:.1f}%" if win_rate else "N/A"
        activity_str = f"{activity:.4f}" if activity else "N/A"
        print(
            f"{ts_str:<20} {hk:<50} {volume_str:<15} {trades_str:<8} {profit_str:<15} {win_rate_str:<10} {activity_str:<10}"
        )


def show_volume():
    """Show prediction volume and trade counts for all miners."""
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT ps.hotkey, ps.weighted_volume, ps.trade_count, ps.timestamp, m.uid
        FROM performance_snapshots ps
        INNER JOIN (
            SELECT hotkey, MAX(timestamp) as max_ts
            FROM performance_snapshots
            GROUP BY hotkey
        ) latest ON ps.hotkey = latest.hotkey AND ps.timestamp = latest.max_ts
        LEFT JOIN miners m ON ps.hotkey = m.hotkey
        ORDER BY ps.weighted_volume DESC NULLS LAST, ps.trade_count DESC NULLS LAST
    """
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No trading activity found in database.")
        return

    print(f"\n📊 Prediction Volume & Trade Counts ({len(rows)} miners):")
    print("=" * 110)
    print(
        f"{'Hotkey':<50} {'UID':<6} {'Volume USD':<15} {'Trades':<10} {'Last Updated':<20}"
    )
    print("-" * 110)

    total_volume = 0
    total_trades = 0
    active_miners = 0

    for hotkey, volume, trades, ts, uid in rows:
        uid_str = str(uid) if uid else "N/A"
        volume_str = f"${volume:,.2f}" if volume else "N/A"
        trades_str = str(trades) if trades else "0"
        ts_str = ts[:19] if ts else "N/A"

        if volume:
            total_volume += volume
            total_trades += trades or 0
            active_miners += 1

        print(
            f"{hotkey:<50} {uid_str:<6} {volume_str:<15} {trades_str:<10} {ts_str:<20}"
        )

    print("-" * 110)
    print(f"Total Active Miners: {active_miners}")
    if total_volume > 0:
        print(f"Total Volume:        ${total_volume:,.2f}")
        print(f"Total Trades:        {total_trades:,}")


def show_miner_details(hotkey: str):
    """Show detailed information about a specific miner."""
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM miners WHERE hotkey = ?", (hotkey,))
    miner = cursor.fetchone()

    if not miner:
        print(f"❌ Miner not found: {hotkey}")
        conn.close()
        return

    print(f"\n🔍 Miner Details: {hotkey}")
    print("=" * 80)
    print(
        "UID:              "
        + (
            {miner[1] if miner[1] else "N/A"}
            if isinstance({miner[1] if miner[1] else "N/A"}, str)
            else (
                str({miner[1] if miner[1] else "N/A"})
                if {miner[1] if miner[1] else "N/A"}
                else "N/A"
            )
        )
    )
    print(f"First Seen:        {miner[3] if miner[3] else 'N/A'}")
    print(f"Last Seen:         {miner[4] if miner[4] else 'N/A'}")
    print(f"Axon IP:           {miner[5] if miner[5] else 'N/A'}")
    print(f"Last Signature:    {miner[2] if miner[2] else 'N/A'}")

    cursor.execute(
        """
        SELECT score, ts, reason
        FROM scoring_runs
        WHERE hotkey = ?
        ORDER BY ts DESC
        LIMIT 1
    """,
        (hotkey,),
    )
    latest_score = cursor.fetchone()

    if latest_score:
        print(
            f"\nLatest EMA Score:   {latest_score[0]:.6f}"
            if latest_score[0]
            else "Latest EMA Score:   N/A"
        )
        print(f"Score Timestamp:    {latest_score[1]}")
        if latest_score[2]:
            print(f"Score Reason:       {latest_score[2]}")

    cursor.execute(
        """
        SELECT weighted_volume, trade_count, realized_profit_usd,
               win_rate, activity_score, timestamp
        FROM performance_snapshots
        WHERE hotkey = ?
        ORDER BY timestamp DESC
        LIMIT 1
    """,
        (hotkey,),
    )
    latest_perf = cursor.fetchone()

    if latest_perf:
        print("\nLatest Performance:")
        print(
            f"  Volume USD:       ${latest_perf[0]:,.2f}"
            if latest_perf[0]
            else "  Volume USD:       N/A"
        )
        print(f"  Trade Count:      {latest_perf[1]}")
        print(
            f"  Profit USD:       ${latest_perf[2]:,.2f}"
            if latest_perf[2]
            else "  Profit USD:       N/A"
        )
        print(
            f"  Win Rate:         {latest_perf[3]*100:.1f}%"
            if latest_perf[3]
            else "  Win Rate:         N/A"
        )
        print(
            f"  Activity Score:   {latest_perf[4]:.4f}"
            if latest_perf[4]
            else "  Activity Score:   N/A"
        )
        print(f"  Timestamp:        {latest_perf[5]}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="WaHoo Validator Database Query Tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    subparsers.add_parser("stats", help="Show database statistics")

    subparsers.add_parser("miners", help="List all registered miners")

    scores_parser = subparsers.add_parser("scores", help="Show latest EMA scores")
    scores_parser.add_argument(
        "--limit", type=int, default=20, help="Number of scores to show"
    )

    subparsers.add_parser("latest-scores", help="Show latest score for each miner")

    perf_parser = subparsers.add_parser(
        "performance", help="Show performance snapshots"
    )
    perf_parser.add_argument(
        "--hotkey", type=str, help="Filter by specific miner hotkey"
    )
    perf_parser.add_argument(
        "--limit", type=int, default=10, help="Number of snapshots to show"
    )

    # Volume command
    subparsers.add_parser(
        "volume", help="Show prediction volume and trade counts for all miners"
    )

    # Miner details command
    miner_parser = subparsers.add_parser(
        "miner", help="Show detailed info for a specific miner"
    )
    miner_parser.add_argument("hotkey", type=str, help="Miner hotkey to query")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "stats":
            show_stats()
        elif args.command == "miners":
            list_miners()
        elif args.command == "scores":
            show_scores(args.limit)
        elif args.command == "latest-scores":
            show_latest_scores()
        elif args.command == "performance":
            show_performance(args.hotkey, args.limit)
        elif args.command == "volume":
            show_volume()
        elif args.command == "miner":
            show_miner_details(args.hotkey)

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
