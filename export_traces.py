"""Export real scenario runs for the web walkthrough.  python export_traces.py

Runs the same gate, planners, and policies as run_demo.py, records every step (including
each rule the gate evaluated), and writes docs/traces.js for docs/index.html to play back.
Nothing in the page is hand-scripted. Re-run this after changing the gate, policies, or planners;
tests/test_traces.py fails if docs/traces.js is stale.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from govdemo import review as rv
from govdemo.agent import run_session
from govdemo.audit import Audit
from govdemo.gate import Gate, PolicyUnresolved
from govdemo.tools import CASES, DANGER, TOOLS
from run_demo import AGENT, ORG, REGISTRY, ROOT, SCENARIOS, failclosed_registry

OUT = ROOT / "docs" / "traces.js"
POLICY_FILES = [AGENT, ORG, REGISTRY / "agency.privacy.pii-redaction-v1.yaml"]


def record(key, reviewer):
    """Run one scenario and capture each step: model-call check, proposal, gate rules, human, result."""
    title, planner_fn, case_id, extra = SCENARIOS[key]
    DANGER.clear()
    registry = failclosed_registry() if extra.get("missing_policy") else REGISTRY
    trace = {"title": title, "case_id": case_id, "reviewer": reviewer, "steps": []}
    required = [p["policy_ref"] for p in yaml.safe_load(AGENT.read_text())["constraints"]["governance_policies"]
                if p.get("required", True)]
    try:
        gate = Gate(AGENT, registry, ORG, case_id)
    except PolicyUnresolved as e:
        trace["startup"] = {"ok": False, "error": str(e), "required": required,
                            "registry": sorted(p.stem for p in Path(registry).glob("*.yaml"))}
        trace.update(status="refused", detail=str(e), draft="", danger=[])
        return trace
    trace["startup"] = {"ok": True, "policies_loaded": gate.policies_loaded, "required": required}
    trace["limits"] = {**gate.limits, **gate.budget}
    trace["case_file"] = json.loads(gate.redact(json.dumps(CASES[case_id])))
    steps = trace["steps"]

    llm_check, gate_check = gate.before_llm_call, gate.check

    def before_llm_call():
        d = llm_check()
        steps.append({"n": len(steps) + 1, "llm": {"calls": gate.llm_calls, "checks": list(gate.checks)}})
        return d

    def check(tool, args):
        d = gate_check(tool, args)
        steps[-1]["gate"] = {"verdict": d.verdict, "rule": d.rule, "reason": d.reason, "message": d.message,
                             "checks": list(gate.checks), "tool_calls": gate.tool_calls}
        return d

    gate.before_llm_call, gate.check = before_llm_call, check

    def approver(review):
        approved = reviewer == "approve"
        steps[-1]["human"] = {"message": review.message, "preview": review.preview, "approved": approved}
        return approved

    audit = Audit(redact=gate.redact)
    audit_log = audit.log

    def log(**fields):
        event = audit_log(**fields)
        steps[-1]["audit"] = {k: v for k, v in event.items() if k != "ts"}
        return event

    audit.log = log

    def wrap(name, fn):
        def run(**kwargs):
            out = fn(**kwargs)
            steps[-1]["result"] = gate.redact(out if isinstance(out, str) else json.dumps(out))
            return out
        return run

    tools = {name: wrap(name, fn) for name, fn in TOOLS.items()}

    after_step = None
    if extra.get("after_step"):
        def after_step(n, g):
            was = g.halted
            extra["after_step"](n, g)
            if g.halted and not was:
                steps[-1]["operator"] = g.halt_reason

    result = run_session(planner_fn(case_id), gate, audit, approver, after_step, tools=tools)
    trace.update(status=result.status, detail=result.detail, draft=result.draft, danger=list(DANGER))
    return trace


def red_herring():
    """The queue plus each reviewer's per-item calls, made in the same order measure() makes them."""
    queue = rv.build_queue()
    out = {"items": [{"id": i.case_id, "income": i.income, "household": i.household,
                      "threshold": rv.threshold_for(i.household), "claimed_eligible": i.claimed_eligible, "correct_eligible": i.correct_eligible,
                      "red_herring": i.is_red_herring} for i in queue],
           "reviewers": []}
    for make in (rv.RubberStamp, rv.Attentive):
        r = make()
        calls = {i.case_id: r.approves(i) for i in queue if i.is_red_herring}
        calls.update({i.case_id: r.approves(i) for i in queue if not i.is_red_herring})
        m = rv.measure(queue, make())
        assert sum(not calls[i.case_id] for i in queue if i.is_red_herring) == m["caught"]
        out["reviewers"].append({**m, "approved": [calls[i.case_id] for i in queue]})
    return out


def build() -> str:
    data = {
        "scenarios": {key: {rev: record(key, rev) for rev in ("approve", "reject")} for key in SCENARIOS},
        "redherring": red_herring(),
        "files": {str(p.relative_to(ROOT)): p.read_text() for p in POLICY_FILES},
    }
    return ("// Generated by export_traces.py from real runs of the gate. Do not edit by hand.\n"
            "window.TRACES = " + json.dumps(data, indent=1) + ";\n")


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT.relative_to(ROOT)}")
