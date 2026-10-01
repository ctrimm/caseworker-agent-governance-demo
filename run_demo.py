"""Run the scenarios:  python run_demo.py [happy|injection|messy|loop|killswitch|failclosed|redherring|all]"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from govdemo import review as rv
from govdemo.agent import careful_planner, hijacked_planner, looping_planner, run_session
from govdemo.audit import Audit
from govdemo.gate import Gate, PolicyUnresolved
from govdemo.tools import DANGER

ROOT = Path(__file__).parent
AGENT = ROOT / "agents" / "caseworker_assistant.agf.yaml"
REGISTRY = ROOT / "policy"
ORG = REGISTRY / "org-baseline.yaml"


def show(result, gate):
    for e in result.events:
        if e["kind"] == "tool_call":
            human = f"  human={e['human']}" if "human" in e else ""
            args = ", ".join(f"{k}={v}" for k, v in e["args"].items())
            print(f"  [{e['verdict'].upper():16}] {e['tool']}({args})")
            print(f"      rule={e['rule']}{human}")
            print(f"      why: {e['why']}")
        else:
            print(f"  [{e['kind'].upper():16}] {e.get('reason', '')}")
    print(f"  -> status: {result.status}" + (f" ({result.detail})" if result.detail else ""))
    if result.draft:
        print(f"  -> draft (redacted): {result.draft}")
    print(f"  -> dangerous tools that actually ran: {DANGER or 'none'}")


# key -> (title, planner, case_id, extra session kwargs). The web walkthrough exports these same runs.
SCENARIOS = {
    "happy": ("happy path: read, calculate, draft, human approves", careful_planner, "C-1001", {}),
    "injection": ("injection: notes try to hijack the agent", hijacked_planner, "C-1003", {}),
    "messy": ("messy data: income missing, agent stops", careful_planner, "C-1002", {}),
    "loop": ("runaway loop: run limit trips", looping_planner, "C-1001", {}),
    "killswitch": ("kill switch: operator halts after step 1", careful_planner, "C-1001",
                   {"after_step": lambda n, g: g.halt() if n == 1 else None}),
    "failclosed": ("fail closed: required policy missing", careful_planner, "C-1001", {"missing_policy": True}),
}


def failclosed_registry():
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(ORG, tmp / ORG.name)  # org baseline present, required privacy policy missing
    return tmp


def session(name, planner_fn, case_id, reviewer="approve", after_step=None, missing_policy=False):
    print(f"\n=== {name} (case {case_id}) ===")
    try:
        gate = Gate(AGENT, failclosed_registry() if missing_policy else REGISTRY, ORG, case_id)
    except PolicyUnresolved as e:
        print(f"  [REFUSED         ] {e}")
        return
    audit = Audit(redact=gate.redact)
    approver = (lambda r: reviewer == "approve")
    result = run_session(planner_fn(case_id), gate, audit, approver, after_step)
    show(result, gate)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("scenario", nargs="?", default="all",
                   choices=["happy", "injection", "messy", "loop", "killswitch", "failclosed", "redherring", "all"])
    p.add_argument("--reviewer", choices=["approve", "reject"], default="approve")
    a = p.parse_args()
    run = lambda s: a.scenario in (s, "all")

    for key, (title, planner_fn, case_id, extra) in SCENARIOS.items():
        if run(key):
            session(title, planner_fn, case_id, a.reviewer, **extra)
    if run("redherring"):
        print("\n=== red herring test (SIMULATION, not real reviewer data) ===")
        queue = rv.build_queue()
        for r in (rv.RubberStamp(), rv.Attentive()):
            m = rv.measure(queue, r)
            print(f"  {m['reviewer']:13} approval rate {m['approval_rate']:.0%}   "
                  f"caught {m['caught']}/{m['red_herrings']} seeded errors ({m['catch_rate']:.0%})")
        print("  Similar approval rates, very different catch rates. Approval rate alone tells you nothing.")


if __name__ == "__main__":
    sys.exit(main())
