# caseworker-agent-governance-demo

A small, runnable companion to the post "Your Guardrails Can't Live Inside the Agent." It shows a
deterministic gate sitting between a scripted caseworker agent and its tools, driven by a real
Agent Format file (`agents/caseworker_assistant.agf.yaml`).

No API key, no network, no LLM. Python 3.10+, two small dependencies.

![routing and flow](docs/flow.gif)

## Run it

```bash
pip install -r requirements.txt
python validate.py                 # agent file vs. the Agent Format JSON schema
python run_demo.py all             # every scenario, with a readable trace
python -m unittest discover -s tests -t .
```

Run one scenario with `python run_demo.py injection`. Add `--reviewer reject` to see the human say no.

## What each scenario demonstrates

| Scenario | What happens | Post lesson |
|---|---|---|
| `happy` | read, calculate, draft. The draft waits on human approval, then runs. | Humans at the irreversible step |
| `injection` | Instructions hidden in the case notes make the (scripted) model try `approve_payout`, a read of another client's case, and `write_record`. All three are denied. The real job still finishes. | Controls live outside the model |
| `messy` | Income is missing. The agent hands off instead of guessing. | Design for missing data |
| `loop` | A model stuck in a loop hits the run limit and is halted. | Bounded budgets |
| `killswitch` | An operator halts the run mid-flight. | Tested kill switch |
| `failclosed` | The agent file marks a policy `required: true`. Remove the policy and the agent refuses to start. | Fail closed |
| `redherring` | Simulated queue of 200 drafts with 5% known-wrong. A rubber-stamp reviewer and an attentive one have similar approval rates and very different catch rates. | Test your oversight |

## How it fits together

- `agents/caseworker_assistant.agf.yaml` declares identity, tools, limits, and which tool needs approval.
  It is the same file shown in the post and passes the official schema.
- `policy/org-baseline.yaml` is org-level policy that is always applied and can only add restrictions:
  a deny list and a per-tool scope rule (a client-file read must match the session's case ID).
- `policy/agency.privacy.pii-redaction-v1.yaml` is the policy the agent file references. It supplies PII redaction.
- `govdemo/gate.py` is the whole enforcement layer. Under 200 lines, no model in it.
- `govdemo/agent.py` has the scripted planners and the loop that routes every proposal through the gate.
- `govdemo/audit.py` writes the why (the agent's stated rationale) next to the what. PII is redacted before logging.
- `govdemo/review.py` is the red herring simulation.

Every proposal takes one path: planner proposes, gate decides (allow, deny, require approval, halt),
allowed calls run, and every decision lands in the audit log.

## What this is not

- **Not a conformant Agent Format runtime.** It reads a handful of the spec's fields and borrows the
  `args_match` operators. The spec's CLI and SDKs were not public when this was written.
- **Not Microsoft's Agent Governance Toolkit.** The policy files here use this toy's own format. If you
  want a real policy engine, use that project or something like it and read its docs.
- **Not a security boundary.** The gate and the agent share a process. Real deployments want container
  isolation and identity on top.
- **`max_token_usage` is declared but not enforced**, because there is no real model to count tokens for.
- **The reviewer models are assumptions.** The red herring numbers show the method, not real behavior.
- **All data is invented.** The income threshold is an illustrative formula, not a poverty-line table.

## Swapping in a real model

Replace a planner in `govdemo/agent.py` with a function that calls your model and yields `Action`
objects from its tool calls, feeding each `Outcome` back in. Leave the gate, audit log, and approval flow alone.
That separation is the point.

## Licenses

Code: MIT (see `LICENSE`). `schema/agentformat-schema.json` is vendored from
[agent-format-schema](https://github.com/agent-format/agent-format-schema) under Apache 2.0; see `NOTICE`.
