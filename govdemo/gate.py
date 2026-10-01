"""The deterministic gate. There is no LLM in this file, on purpose.

It reads the same .agf.yaml a reviewer reads, layers policy on top, and answers one
question for every proposed tool call: allow, deny, require approval, or halt.

This is a teaching toy. It borrows field names from the Agent Format spec
(action_space, constraints, approval, args_match) but it is not a conformant
Agent Format runtime.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

ALLOW, DENY, APPROVE, HALT = "allow", "deny", "require_approval", "halt"


@dataclass(frozen=True)
class Decision:
    verdict: str
    rule: str
    reason: str
    message: str = ""


class PolicyUnresolved(RuntimeError):
    """A policy the agent file marks required could not be found."""


# --- approval conditions (same operators as the Agent Format args_match block) ---

def _match_one(expected, actual) -> bool:
    if not isinstance(expected, dict):
        return actual == expected
    for op, v in expected.items():
        if op == "gt" and not actual > v:
            return False
        if op == "gte" and not actual >= v:
            return False
        if op == "lt" and not actual < v:
            return False
        if op == "lte" and not actual <= v:
            return False
        if op == "ne" and not actual != v:
            return False
        if op == "in" and actual not in v:
            return False
        if op == "not_in" and actual in v:
            return False
        if op == "pattern" and not re.search(v, str(actual)):
            return False
    return True


def approval_required(spec, args: dict) -> bool:
    """approval: true / {} always requires. false / missing never does.
    A condition makes it conditional. If a condition cannot be evaluated, ask a human."""
    if spec is None or spec is False:
        return False
    if spec is True:
        return True
    cond = spec.get("condition")
    if cond is None:
        return True
    groups = cond if isinstance(cond, list) else [cond]
    try:
        return any(
            all(_match_one(exp, args.get(key)) for key, exp in g.get("args_match", {}).items())
            for g in groups
        )
    except Exception:
        return True


def render_message(template: str | None, tool: str, args: dict) -> str:
    if not template:
        return f"Approve {tool}({', '.join(f'{k}={v}' for k, v in args.items())})?"

    def sub(m):
        return str(args.get(m.group(1), ""))

    out = re.sub(r"\{\{\s*tool_args\.([\w]+)\s*\}\}", sub, template)
    return out.replace("{{tool_name}}", tool)


# --- the gate ---

class Gate:
    def __init__(self, agent_path, registry_dir, org_policy_path, case_id, clock=time.monotonic):
        self.agent = yaml.safe_load(Path(agent_path).read_text())
        self.case_id = case_id
        self.clock = clock
        self.start = clock()
        self.tools = {t["alias"]: t for t in self.agent["action_space"]["local_tools"]}
        constraints = self.agent.get("constraints", {})
        self.budget = constraints.get("budget", {})
        self.limits = constraints.get("limits", {})
        self.llm_calls = 0
        self.tool_calls = 0
        self.halted = False
        self.halt_reason = ""
        self.checks: list[dict] = []  # rules evaluated for the latest call, in order (for tracing only)

        org = yaml.safe_load(Path(org_policy_path).read_text())
        self.policies_loaded = [org.get("name", Path(org_policy_path).stem)]
        self.deny_tools = set(org.get("deny_tools", []))
        self.org_approval = set(org.get("approval_tools", []))
        self.scope = dict(org.get("scope", {}))
        self.redactions: dict[str, str] = {}
        for ref in constraints.get("governance_policies", []):
            path = Path(registry_dir) / f"{ref['policy_ref']}.yaml"
            if not path.exists():
                if ref.get("required", True):
                    raise PolicyUnresolved(
                        f"required policy '{ref['policy_ref']}' not found; refusing to run"
                    )
                continue
            pol = yaml.safe_load(path.read_text())
            self.deny_tools |= set(pol.get("deny_tools", []))
            self.org_approval |= set(pol.get("approval_tools", []))
            self.scope.update(pol.get("scope", {}))
            self.redactions.update(pol.get("redact", {}))
            self.policies_loaded.append(ref["policy_ref"])

    # kill switch
    def halt(self, reason="kill switch pulled by operator"):
        self.halted = True
        self.halt_reason = reason

    def redact(self, text: str) -> str:
        for name, pattern in self.redactions.items():
            text = re.sub(pattern, f"[REDACTED:{name}]", text)
        return text

    def _passed(self, rule: str, detail: str):
        self.checks.append({"rule": rule, "result": "pass", "detail": detail})

    def _decide(self, d: Decision) -> Decision:
        self.checks.append({"rule": d.rule, "result": d.verdict, "detail": d.reason})
        return d

    def before_llm_call(self):
        """Called before every model step. Returns a HALT decision or None."""
        self.checks = []
        if self.halted:
            return self._decide(Decision(HALT, "kill-switch", self.halt_reason))
        self._passed("kill-switch", "not pulled")
        self.llm_calls += 1
        cap = self.limits.get("max_llm_calls")
        if cap is not None and self.llm_calls > cap:
            return self._decide(Decision(HALT, "limits.max_llm_calls", f"more than {cap} model calls in one run"))
        self._passed("limits.max_llm_calls", f"model call {self.llm_calls} of {cap}")
        return None

    def check(self, tool: str, args: dict) -> Decision:
        """Rules run in order. The first one that objects decides; later rules are not evaluated."""
        self.checks = []
        if self.halted:
            return self._decide(Decision(HALT, "kill-switch", self.halt_reason))
        self._passed("kill-switch", "not pulled")
        max_s = self.budget.get("max_duration_seconds")
        elapsed = self.clock() - self.start
        if max_s is not None and elapsed > max_s:
            return self._decide(Decision(HALT, "budget.max_duration_seconds", f"run exceeded {max_s}s"))
        self._passed("budget.max_duration_seconds", f"{elapsed:.0f}s of {max_s}s used")
        self.tool_calls += 1
        cap = self.limits.get("max_tool_calls")
        if cap is not None and self.tool_calls > cap:
            return self._decide(Decision(HALT, "limits.max_tool_calls", f"more than {cap} tool calls in one run"))
        self._passed("limits.max_tool_calls", f"tool call {self.tool_calls} of {cap}")

        if tool not in self.tools:
            return self._decide(Decision(DENY, "default-deny", f"'{tool}' is not in this agent's action_space"))
        self._passed("default-deny", f"'{tool}' is declared in action_space")
        if tool in self.deny_tools:
            return self._decide(Decision(DENY, "org.deny_tools", f"'{tool}' is blocked by org policy"))
        self._passed("org.deny_tools", f"'{tool}' is not on the org deny list")
        rule = self.scope.get(tool)
        if rule and args.get(rule["arg"]) != self.case_id:
            return self._decide(Decision(
                DENY, "org.scope",
                f"{rule['arg']}={args.get(rule['arg'])!r} is outside this session's case {self.case_id!r}",
            ))
        self._passed("org.scope", f"{rule['arg']} matches case {self.case_id!r}" if rule else "no scope rule for this tool")

        spec = self.tools[tool].get("approval")
        agent_says = approval_required(spec, args)
        org_says = tool in self.org_approval
        if agent_says or org_says:
            template = spec.get("message_template") if isinstance(spec, dict) else None
            why = "org policy" if org_says and not agent_says else "agent file"
            return self._decide(Decision(APPROVE, "approval", f"approval required by {why}",
                                         render_message(template, tool, args)))
        self._passed("approval", "neither the agent file nor org policy requires a human")
        return self._decide(Decision(ALLOW, "allow-listed", "tool is declared and no rule objects"))
