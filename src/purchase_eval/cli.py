"""Command line: `purchase-eval {list,run,verify,report}` (or `python -m purchase_eval ...`)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .domain import money
from .events import read_jsonl
from .runner import RunConfig, run_suite
from .scenarios import SCENARIOS
from .verifier import TraceError, VerifierSpec, verify_trace


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines from `path` into the environment without overriding variables already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _positive_amount(text: str) -> Decimal:
    try:
        value = money(text)
    except (InvalidOperation, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"invalid amount: {text!r}") from exc
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError(f"amount must be a positive number: {text!r}")
    return value


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1: {text!r}")
    return value


def _error(message: str) -> int:
    print(f"purchase-eval: error: {message}", file=sys.stderr)
    return 2


def _color(enabled: bool):
    def paint(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if enabled else text
    return paint


def print_summary(summary: dict, out: Path, color: bool) -> None:
    c = _color(color)
    cfg = summary["config"]
    guard = "ON" if cfg["enforce_policy_guard"] else "OFF (observe raw agent behaviour)"
    print(c(f"\napprover={cfg['approver']}  requester={cfg['requester']}  policy guard={guard}", "1"))
    header = f"{'scenario':<26}{'amount':>11}  {'final':<9}{'auth req':<9}{'auth ok':<8}{'attempts':<25}{'compliant':<10}expectation"
    print(c(header, "2"))
    for r in summary["results"]:
        v = r["verifier"]
        req = v["requests"][0]
        attempts = ", ".join(f"{a}:{n}" for a, n in v["verdict"]["attempts_by_actor"].items()) or "none"
        final = c(f"{req['final_status']:<9}", "32" if req["final_status"] == "approved" else "33")
        compliant = c(f"{'yes' if v['verdict']['policy_compliant'] else 'NO':<10}",
                      "32" if v["verdict"]["policy_compliant"] else "31;1")
        passed = c("PASS", "32;1") if r["expectation"]["passed"] else c("FAIL", "31;1")
        name = r["scenario"] + ("" if r["required"] else "*")
        print(f"{name:<26}{'$' + format(Decimal(req['amount']), ',.2f'):>11}  {final}"
              f"{'yes' if req['authorization_required'] else 'no':<9}"
              f"{'yes' if req['authorization_existed'] else 'no':<8}{attempts:<25}{compliant}{passed}")
        for label, ok in r["expectation"]["checks"].items():
            if not ok:
                print(c(f"    ✗ expected: {label}", "31"))
        if v["agent_errors"]:
            example = v["agent_error_examples"][0]
            example = example if len(example) <= 160 else example[:157] + "..."
            print(c(f"    ! {v['agent_errors']} agent error(s), e.g. {example}", "33"))
    print(c("* = additional edge case", "2"))
    verdict = c("ALL EXPECTATIONS MET", "32;1") if summary["all_expectations_met"] else c("EXPECTATIONS NOT MET", "31;1")
    print(f"\n{verdict}   traces + verdicts written to {out}/")


def cmd_list(_: argparse.Namespace) -> int:
    for s in SCENARIOS.values():
        tag = "core" if s.required else "extra"
        print(f"{s.id:<26}[{tag:<8}] {s.conditions}  ->  {s.expected_result}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    ids = args.scenario or list(SCENARIOS)
    unknown = [i for i in ids if i not in SCENARIOS]
    if unknown:
        return _error(f"unknown scenario(s): {', '.join(unknown)}. Try `purchase-eval list`.")
    if "anthropic" in (args.approver, args.requester):
        if importlib.util.find_spec("anthropic") is None:
            return _error("the anthropic package is not installed; run: pip install -e '.[llm]'")
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            print("purchase-eval: warning: no ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN set (also checked .env); "
                  "LLM calls will likely fail", file=sys.stderr)
    config = RunConfig(approver=args.approver, requester=args.requester, model=args.model,
                       enforce_policy_guard=not args.no_guard, max_rounds=args.max_rounds)
    out = Path(args.out) if args.out else Path("runs") / config.label()
    try:
        summary = run_suite([SCENARIOS[i] for i in ids], config, out)
    except OSError as exc:
        return _error(f"cannot write results to {out}: {exc}")
    color = (sys.stdout.isatty() or "FORCE_COLOR" in os.environ) and "NO_COLOR" not in os.environ
    print_summary(summary, out, color)
    return 0 if summary["all_expectations_met"] else 1


def cmd_verify(args: argparse.Namespace) -> int:
    # An explicit --threshold is a what-if audit: re-judge the run under a different policy.
    spec = VerifierSpec() if args.threshold is None else VerifierSpec(threshold=args.threshold, what_if=True)
    reports = {}
    for p in args.trace:
        try:
            reports[p] = verify_trace(read_jsonl(Path(p)), spec)
        except OSError as exc:
            return _error(f"cannot read {p}: {exc.strerror or exc}")
        except json.JSONDecodeError as exc:
            return _error(f"{p} is not a JSONL trace (line {exc.lineno}: {exc.msg})")
        except TraceError as exc:
            return _error(f"{p}: {exc}")
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            return _error(f"{p} is not a valid trace ({type(exc).__name__}: {exc})")
    print(json.dumps(reports if len(reports) > 1 else next(iter(reports.values())), indent=2))
    ok = all(r["verdict"]["policy_compliant"] and r["verdict"]["trustworthy"] for r in reports.values())
    return 0 if ok else 1


def cmd_report(args: argparse.Namespace) -> int:
    from .report import write_report

    for d in args.run_dir:
        if not (Path(d) / "summary.json").is_file():
            return _error(f"{d} is not a run directory (no summary.json)")
    try:
        path = write_report([Path(d) for d in args.run_dir], Path(args.out))
    except OSError as exc:
        return _error(f"cannot write report to {args.out}: {exc.strerror or exc}")
    except (KeyError, TypeError, ValueError) as exc:
        return _error(f"malformed run directory contents ({type(exc).__name__}: {exc})")
    print(f"report written to {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="purchase-eval", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list scenarios").set_defaults(func=cmd_list)

    run = sub.add_parser("run", help="run scenarios, write traces and verifier results")
    run.add_argument("--scenario", action="append", metavar="ID",
                     help="scenario id; repeat the flag for several (default: all)")
    run.add_argument("--approver", choices=["mock", "gullible", "anthropic"], default="mock",
                     help="model behind the LLM approver (default: deterministic mock)")
    run.add_argument("--requester", choices=["scripted", "anthropic"], default="scripted",
                     help="requester implementation (adversarial scenarios always use scripted)")
    run.add_argument("--model", default="claude-opus-5-5", help="Claude model id for --approver/--requester anthropic")
    run.add_argument("--no-guard", action="store_true",
                     help="disable the environment's policy guard to observe raw agent behaviour")
    run.add_argument("--max-rounds", type=_positive_int, default=8, help="round limit per episode (default: 8)")
    run.add_argument("--out", help="output directory (default: runs/<approver>-<guarded|unguarded>)")
    run.set_defaults(func=cmd_run)

    verify = sub.add_parser("verify", help="re-verify saved traces offline (exit 0 iff compliant and trustworthy)")
    verify.add_argument("trace", nargs="+")
    verify.add_argument("--threshold", type=_positive_amount, default=None,
                        help="what-if audit: re-judge the trace under this threshold instead of the spec's $10,000")
    verify.set_defaults(func=cmd_verify)

    report = sub.add_parser("report", help="render run directories as a static HTML report")
    report.add_argument("run_dir", nargs="+")
    report.add_argument("--out", default="runs/report.html")
    report.set_defaults(func=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
