#!/usr/bin/env python3
import json
import argparse
from monitor import AsterDexMonitor
from legacy.funding_bot import configure_logging
import logging

def format_currency(value, precision=2):
    """Format currency values"""
    try:
        return f"${float(value):,.{precision}f}"
    except:
        return "$0.00"

def format_percentage(value, precision=2):
    """Format percentage values"""
    try:
        return f"{float(value)*100:.{precision}f}%"
    except:
        return "0.00%"

def print_section(title, width=60):
    """Print section header"""
    print("\n" + "="*width)
    print(f" {title} ".center(width))
    print("="*width)

def print_subsection(title):
    """Print subsection header"""
    print(f"\n📊 {title}")
    print("-" * 40)

def display_portfolio_summary(summary):
    """Display portfolio overview"""
    print_section("📈 PORTFOLIO OVERVIEW")

    portfolio = summary.get("portfolio", {})
    spot = summary.get("spot", {})
    futures = summary.get("futures", {})

    print(f"Total Portfolio Value: {format_currency(portfolio.get('total_usd', 0))}")
    print(f"Spot Holdings:         {format_currency(spot.get('total_usd', 0))} ({format_percentage(portfolio.get('spot_ratio', 0))})")
    print(f"Futures Balance:       {format_currency(futures.get('total_usd', 0))} ({format_percentage(portfolio.get('futures_ratio', 0))})")

    # Show spot balances
    spot_balances = spot.get("balance", [])
    if spot_balances:
        print_subsection("Spot Balances")
        for balance in spot_balances[:10]:  # Show top 10
            asset = balance.get("asset", "")
            free = float(balance.get("free", 0))
            locked = float(balance.get("locked", 0))
            if free > 0 or locked > 0:
                print(f"  {asset:<12} Free: {free:>12.4f}  Locked: {locked:>12.4f}")

def display_risk_metrics(risk):
    """Display risk information"""
    print_section("⚖️  RISK METRICS")

    leverage = risk.get("effective_leverage", 0)
    risk_level = risk.get("risk_level", "UNKNOWN")
    exposure = risk.get("total_notional_exposure", 0)
    margin_balance = risk.get("total_margin_balance", 0)

    # Risk level indicator
    risk_indicator = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "EXTREME": "🔴"}.get(risk_level, "❓")

    print(f"Effective Leverage:  {leverage:.2f}x")
    print(f"Risk Level:          {risk_indicator} {risk_level}")
    print(f"Total Exposure:      {format_currency(exposure)}")
    print(f"Margin Balance:      {format_currency(margin_balance)}")

    if margin_balance > 0:
        margin_ratio = margin_balance / exposure if exposure > 0 else 0
        print(f"Margin Ratio:        {format_percentage(margin_ratio)}")

def display_positions(pnl):
    """Display current positions"""
    print_section("📈 CURRENT POSITIONS")

    positions = pnl.get("positions", [])
    total_pnl = pnl.get("total_unrealized_pnl", "0")

    pnl_indicator = "🟢" if float(total_pnl) >= 0 else "🔴"
    print(f"Total Unrealized PnL: {pnl_indicator} {format_currency(total_pnl)}")

    if not positions:
        print("No open positions")
        return

    print(f"\n{'Symbol':<12} {'Side':<6} {'Size':<12} {'Entry':<10} {'Mark':<10} {'PnL':<12}")
    print("-" * 70)

    for pos in positions:
        symbol = pos.get("symbol", "")[:11]
        side = pos.get("side", "")
        size = abs(float(pos.get("position_amt", 0)))
        entry_price = float(pos.get("entry_price", 0))
        mark_price = float(pos.get("mark_price", 0))
        unrealized_pnl = float(pos.get("unrealized_pnl", 0))

        pnl_indicator = "🟢" if unrealized_pnl >= 0 else "🔴"

        print(f"{symbol:<12} {side:<6} {size:>10.4f} {entry_price:>8.4f} {mark_price:>8.4f} {pnl_indicator} {unrealized_pnl:>9.2f}")

def display_funding_rates(summary):
    """Display funding rates"""
    print_section("💰 FUNDING RATES")

    funding = summary.get("funding", [])
    if not funding:
        print("No funding data available")
        return

    print(f"{'Symbol':<12} {'Current Rate':<15} {'Next Funding'}")
    print("-" * 40)

    for item in funding:
        symbol = item.get("symbol", "")
        premium = item.get("premium_index", {})
        rate = premium.get("lastFundingRate", "0")
        rate_percent = float(rate) * 100

        rate_indicator = "🟢" if rate_percent >= 0 else "🔴"
        next_funding = premium.get("nextFundingTime", "N/A")

        print(f"{symbol:<12} {rate_indicator} {rate_percent:>12.4f}% {next_funding}")

def display_hedging_efficiency(hedging):
    """Display hedging information"""
    print_section("🎯 HEDGING EFFICIENCY")

    avg_efficiency = hedging.get("average_efficiency", 0) * 100
    total_pairs = hedging.get("total_pairs", 0)
    pairs = hedging.get("hedged_pairs", [])

    efficiency_indicator = "🟢" if avg_efficiency > 90 else "🟡" if avg_efficiency > 70 else "🔴"

    print(f"Average Efficiency: {efficiency_indicator} {avg_efficiency:.1f}%")
    print(f"Hedged Pairs:       {total_pairs}")

    if pairs:
        print(f"\n{'Symbol':<12} {'Spot Qty':<12} {'Futures Qty':<12} {'Ratio':<8} {'Status'}")
        print("-" * 60)

        for pair in pairs:
            symbol = pair.get("symbol", "")[:11]
            spot_qty = pair.get("spot_qty", 0)
            futures_qty = pair.get("futures_qty", 0)
            ratio = pair.get("hedge_ratio", 0)

            if pair.get("is_over_hedged"):
                status = "🔴 OVER"
            elif pair.get("is_under_hedged"):
                status = "🟡 UNDER"
            else:
                status = "🟢 OK"

            print(f"{symbol:<12} {spot_qty:>10.4f} {futures_qty:>12.4f} {ratio:>6.2f} {status}")

def display_funding_payments(payments):
    """Display recent funding payments"""
    print_section("💸 RECENT FUNDING PAYMENTS (Last 7 Days)")

    if not payments:
        print("No recent funding payments")
        return

    total_income = sum(float(p.get("income", 0)) for p in payments)
    income_indicator = "🟢" if total_income >= 0 else "🔴"

    print(f"Total Funding Income: {income_indicator} {format_currency(total_income, 4)}")

    print(f"\n{'Symbol':<12} {'Income':<12} {'Date'}")
    print("-" * 35)

    from datetime import datetime

    for payment in payments[-10:]:  # Show last 10
        symbol = payment.get("symbol", "")[:11]
        income = float(payment.get("income", 0))
        timestamp = int(payment.get("time", 0))

        income_indicator = "🟢" if income >= 0 else "🔴"
        date_str = datetime.fromtimestamp(timestamp/1000).strftime("%m/%d %H:%M")

        print(f"{symbol:<12} {income_indicator} {income:>10.4f} {date_str}")

def main():
    parser = argparse.ArgumentParser(description="AsterDex Position Monitor CLI")
    parser.add_argument("--json", action="store_true", help="Output raw JSON data")
    parser.add_argument("--section", choices=["portfolio", "risk", "positions", "funding", "hedging", "payments"],
                       help="Show only specific section")
    parser.add_argument("--log-level", default="ERROR", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")

    args = parser.parse_args()

    configure_logging(args.log_level)

    try:
        monitor = AsterDexMonitor()

        # Fetch all data
        summary = monitor.get_account_summary()
        risk = monitor.get_risk_metrics()
        pnl = monitor.get_position_pnl()
        hedging = monitor.get_hedging_efficiency()
        payments = monitor.get_funding_payments(days=7)

        dashboard_data = {
            "summary": summary,
            "risk": risk,
            "pnl": pnl,
            "hedging": hedging,
            "funding_payments": payments,
            "timestamp": summary.get("timestamp")
        }

        if args.json:
            print(json.dumps(dashboard_data, indent=2))
            return

        print("🚀 AsterDex Position Monitor")
        print(f"Last updated: {summary.get('timestamp', 'N/A')}")

        if args.section:
            if args.section == "portfolio":
                display_portfolio_summary(summary)
            elif args.section == "risk":
                display_risk_metrics(risk)
            elif args.section == "positions":
                display_positions(pnl)
            elif args.section == "funding":
                display_funding_rates(summary)
            elif args.section == "hedging":
                display_hedging_efficiency(hedging)
            elif args.section == "payments":
                display_funding_payments(payments)
        else:
            # Show all sections
            display_portfolio_summary(summary)
            display_risk_metrics(risk)
            display_positions(pnl)
            display_funding_rates(summary)
            display_hedging_efficiency(hedging)
            display_funding_payments(payments)

    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
