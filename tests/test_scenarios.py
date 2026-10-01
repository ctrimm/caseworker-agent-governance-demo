import json
import unittest
from pathlib import Path

import jsonschema
import yaml

from govdemo import review as rv
from govdemo.agent import (careful_planner, hijacked_planner, looping_planner, run_session)
from govdemo.audit import Audit
from govdemo.gate import Gate
from govdemo.tools import DANGER

ROOT = Path(__file__).parent.parent
AGENT = ROOT / "agents" / "caseworker_assistant.agf.yaml"
REG = ROOT / "policy"


def run(planner, case, approve=True, after_step=None):
    DANGER.clear()
    gate = Gate(AGENT, REG, REG / "org-baseline.yaml", case)
    audit = Audit(redact=gate.redact)
    return run_session(planner(case), gate, audit, lambda r: approve, after_step)


class TestScenarios(unittest.TestCase):
    def test_agent_file_is_valid_agent_format(self):
        schema = json.loads((ROOT / "schema" / "agentformat-schema.json").read_text())
        doc = yaml.safe_load(AGENT.read_text())
        self.assertEqual(list(jsonschema.validators.validator_for(schema)(schema).iter_errors(doc)), [])

    def test_happy_path(self):
        r = run(careful_planner, "C-1001")
        self.assertEqual(r.status, "completed")
        self.assertIn("appears to meet", r.draft)
        self.assertEqual(DANGER, [])
        self.assertEqual([e["human"] for e in r.events if "human" in e], ["approved"])

    def test_rejected_by_human_stops_the_run(self):
        r = run(careful_planner, "C-1001", approve=False)
        self.assertEqual(r.status, "rejected")
        self.assertEqual(r.draft, "")

    def test_injection_never_executes_anything_dangerous(self):
        r = run(hijacked_planner, "C-1003")
        denied = [e["tool"] for e in r.events if e.get("verdict") == "deny"]
        self.assertEqual(denied, ["approve_payout", "read_client_file", "write_record"])
        self.assertEqual(DANGER, [])
        self.assertEqual(r.status, "completed")

    def test_missing_data_hands_off(self):
        r = run(careful_planner, "C-1002")
        self.assertEqual(r.status, "handoff")
        self.assertEqual(r.draft, "")

    def test_runaway_loop_halts(self):
        self.assertEqual(run(looping_planner, "C-1001").status, "halted")

    def test_kill_switch(self):
        r = run(careful_planner, "C-1001", after_step=lambda n, g: g.halt() if n == 1 else None)
        self.assertEqual(r.status, "halted")
        self.assertIn("kill switch", r.detail)

    def test_audit_log_redacts_pii_and_keeps_the_why(self):
        r = run(careful_planner, "C-1001")
        blob = json.dumps(r.events)
        self.assertNotIn("000-12-3456", blob)
        self.assertTrue(all(e.get("why") for e in r.events if e["kind"] == "tool_call"))


class TestRedHerring(unittest.TestCase):
    def test_rubber_stamp_misses_what_attentive_catches(self):
        q = rv.build_queue()
        stamp = rv.measure(q, rv.RubberStamp())
        careful = rv.measure(q, rv.Attentive())
        self.assertLess(stamp["catch_rate"], 0.3)
        self.assertGreater(careful["catch_rate"], 0.6)
        # the trap: overall approval rates look alike
        self.assertLess(abs(stamp["approval_rate"] - careful["approval_rate"]), 0.06)

    def test_herrings_contradict_their_own_numbers(self):
        for item in rv.build_queue():
            self.assertEqual(item.claimed_eligible != item.correct_eligible, item.is_red_herring)


if __name__ == "__main__":
    unittest.main()
