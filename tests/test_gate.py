import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from govdemo.gate import (ALLOW, APPROVE, DENY, HALT, Gate, PolicyUnresolved,
                          approval_required, render_message)

ROOT = Path(__file__).parent.parent
AGENT = ROOT / "agents" / "caseworker_assistant.agf.yaml"
REG = ROOT / "policy"
ORG = REG / "org-baseline.yaml"


def gate(case="C-1001", agent=AGENT, org=ORG, reg=REG, **kw):
    return Gate(agent, reg, org, case, **kw)


def write_agent(mutate) -> Path:
    doc = copy.deepcopy(yaml.safe_load(AGENT.read_text()))
    mutate(doc)
    p = Path(tempfile.mkdtemp()) / "a.agf.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


class TestGate(unittest.TestCase):
    def test_declared_tool_is_allowed(self):
        self.assertEqual(gate().check("read_client_file", {"case_id": "C-1001"}).verdict, ALLOW)

    def test_undeclared_tool_is_denied_by_default(self):
        d = gate().check("approve_payout", {})
        self.assertEqual((d.verdict, d.rule), (DENY, "default-deny"))

    def test_org_deny_beats_the_agent_file(self):
        def declare(doc):
            doc["action_space"]["local_tools"].append({"alias": "write_record"})
        d = gate(agent=write_agent(declare)).check("write_record", {})
        self.assertEqual((d.verdict, d.rule), (DENY, "org.deny_tools"))

    def test_scope_blocks_other_cases(self):
        d = gate().check("read_client_file", {"case_id": "C-2000"})
        self.assertEqual((d.verdict, d.rule), (DENY, "org.scope"))

    def test_draft_requires_approval_with_rendered_message(self):
        d = gate().check("draft_determination_letter", {})
        self.assertEqual(d.verdict, APPROVE)
        self.assertIn("Approve this draft letter", d.message)

    def test_agent_cannot_opt_out_of_org_approval(self):
        def relax(doc):
            for t in doc["action_space"]["local_tools"]:
                if t["alias"] == "calculate_income_threshold":
                    t["approval"] = False
        org = Path(tempfile.mkdtemp()) / "org.yaml"
        org.write_text(yaml.safe_dump({"approval_tools": ["calculate_income_threshold"]}))
        d = gate(agent=write_agent(relax), org=org).check("calculate_income_threshold", {})
        self.assertEqual(d.verdict, APPROVE)

    def test_tool_call_limit_halts(self):
        g = gate()
        verdicts = [g.check("read_client_file", {"case_id": "C-1001"}).verdict for _ in range(13)]
        self.assertEqual(verdicts[:12], [ALLOW] * 12)
        self.assertEqual(verdicts[12], HALT)

    def test_llm_call_limit_halts(self):
        g = gate()
        results = [g.before_llm_call() for _ in range(9)]
        self.assertTrue(all(r is None for r in results[:8]))
        self.assertEqual(results[8].verdict, HALT)

    def test_duration_budget_halts(self):
        t = [0.0]
        g = gate(clock=lambda: t[0])
        t[0] = 121.0
        self.assertEqual(g.check("read_client_file", {"case_id": "C-1001"}).verdict, HALT)

    def test_kill_switch(self):
        g = gate()
        g.halt()
        self.assertEqual(g.check("read_client_file", {"case_id": "C-1001"}).verdict, HALT)
        self.assertEqual(g.before_llm_call().verdict, HALT)

    def test_required_policy_missing_fails_closed(self):
        empty = Path(tempfile.mkdtemp())
        with self.assertRaises(PolicyUnresolved):
            gate(reg=empty)

    def test_optional_policy_missing_is_skipped(self):
        def optional(doc):
            doc["constraints"]["governance_policies"][0]["required"] = False
        g = gate(agent=write_agent(optional), reg=Path(tempfile.mkdtemp()))
        self.assertEqual(g.redactions, {})

    def test_redaction(self):
        text = "SSN 000-12-3456 phone 555-010-0199 dob 4/2/1988"
        out = gate().redact(text)
        self.assertNotIn("000-12-3456", out)
        self.assertNotIn("555-010-0199", out)
        self.assertNotIn("4/2/1988", out)
        self.assertIn("[REDACTED:SSN]", out)


class TestApprovalConditions(unittest.TestCase):
    def test_forms(self):
        self.assertTrue(approval_required(True, {}))
        self.assertTrue(approval_required({}, {}))
        self.assertFalse(approval_required(False, {}))
        self.assertFalse(approval_required(None, {}))

    def test_and_group(self):
        spec = {"condition": {"args_match": {"amount": {"gt": 1000}, "currency": "USD"}}}
        self.assertTrue(approval_required(spec, {"amount": 5000, "currency": "USD"}))
        self.assertFalse(approval_required(spec, {"amount": 5000, "currency": "EUR"}))

    def test_or_of_ands(self):
        spec = {"condition": [{"args_match": {"amount": {"gt": 1000}}},
                              {"args_match": {"kind": "external"}}]}
        self.assertTrue(approval_required(spec, {"amount": 1, "kind": "external"}))
        self.assertFalse(approval_required(spec, {"amount": 1, "kind": "internal"}))

    def test_unevaluable_condition_asks_a_human(self):
        spec = {"condition": {"args_match": {"amount": {"gt": 1000}}}}
        self.assertTrue(approval_required(spec, {}))  # missing arg -> cannot compare -> ask

    def test_message_template(self):
        self.assertEqual(render_message("Pay {{tool_args.amount}}?", "pay", {"amount": 5}), "Pay 5?")


if __name__ == "__main__":
    unittest.main()
