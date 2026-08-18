#!/usr/bin/env python3
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from app.schemas import InvestorPortfolio
from app.evidence import build_evidence_bundle
from app.llm_layer import generate_insights
from report import build_report

BASE = Path(__file__).parent


def load_risk_seed() -> dict:
    with open(BASE / "data" / "risk_seed.json") as f:
        raw = json.load(f)
    raw.pop("_source_note", None)
    return raw


def run_one(portfolio_dict: dict, risk_seed: dict) -> dict:
    t0 = time.time()
    try:
        portfolio = InvestorPortfolio(**portfolio_dict)
    except ValidationError as e:
        return {
            "portfolio_no": portfolio_dict.get("portfolio_no", "UNKNOWN"),
            "status": "rejected",
            "reason": "Input failed schema validation - missing or malformed compulsory fields.",
            "validation_errors": json.loads(e.json()),
        }

    nav_note = "input-supplied (no live NAV fetch in this run)"
    bundle = build_evidence_bundle(portfolio, risk_seed, nav_note)
    output = generate_insights(bundle, investor_notes=portfolio.notes)
    elapsed = round(time.time() - t0, 3)

    return {
        "portfolio_no": portfolio.portfolio_no,
        "status": "ok",
        "elapsed_seconds": elapsed,
        "evidence_bundle": json.loads(bundle.model_dump_json()),
        "insight_output": json.loads(output.model_dump_json()),
    }


def main():
    ap = argparse.ArgumentParser(description="Mutual Fund Portfolio Intelligence System")
    ap.add_argument("--portfolio", type=str, default=None,
                     help="Path to a JSON file with either one portfolio object or {'portfolios': [...]}")
    ap.add_argument("--portfolio-no", type=str, default=None,
                     help="If the file has multiple portfolios, only run this one")
    ap.add_argument("--out", type=str, default=str(BASE / "output" / "results.json"))
    ap.add_argument("--pdf-out", type=str, default=str(BASE / "output" / "portfolio_report.pdf"))
    ap.add_argument("--no-pdf", action="store_true", help="Skip generating the PDF report")
    ap.add_argument("--summary-only", action="store_true", help="Print only the insight titles, not full JSON")
    args = ap.parse_args()

    portfolio_path = Path(args.portfolio) if args.portfolio else BASE / "data" / "sample_portfolios.json"
    with open(portfolio_path) as f:
        raw = json.load(f)

    portfolios = raw["portfolios"] if "portfolios" in raw else [raw]
    if args.portfolio_no:
        portfolios = [p for p in portfolios if p.get("portfolio_no") == args.portfolio_no]
        if not portfolios:
            print(f"No portfolio with portfolio_no={args.portfolio_no} found in {portfolio_path}")
            sys.exit(1)

    risk_seed = load_risk_seed()
    results = [run_one(p, risk_seed) for p in portfolios]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2, default=str)

    for r in results:
        print(f"\n{'='*70}\n{r['portfolio_no']}  [{r['status']}]")
        if r["status"] == "rejected":
            print(f"  Rejected: {r['reason']}")
            continue
        print(f"  mode={r['insight_output']['generation_mode']}  "
              f"elapsed={r['elapsed_seconds']}s  "
              f"warnings={len(r['insight_output']['warnings'])}")
        if args.summary_only:
            for ins in r["insight_output"]["insights"]:
                print(f"    [{ins['priority']}] {ins['title']}")
        else:
            for ins in r["insight_output"]["insights"]:
                print(f"\n  [{ins['priority']}] {ins['title']}  ({ins['category']})")
                print(f"      {ins['explanation']}")
            if r["insight_output"]["warnings"]:
                print(f"\n  Warnings:")
                for w in r["insight_output"]["warnings"]:
                    print(f"    - {w}")

    print(f"\n{'='*70}\nFull results written to {args.out}")

    if not args.no_pdf:
        Path(args.pdf_out).parent.mkdir(parents=True, exist_ok=True)
        build_report(results, args.pdf_out)
        print(f"PDF report written to {args.pdf_out}")


if __name__ == "__main__":
    main()
