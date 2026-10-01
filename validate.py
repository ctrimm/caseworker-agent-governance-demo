"""Validate the agent file against the vendored Agent Format JSON schema.  python validate.py [file...]"""
import json
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).parent
schema = json.loads((ROOT / "schema" / "agentformat-schema.json").read_text())
files = sys.argv[1:] or [str(p) for p in (ROOT / "agents").glob("*.agf.yaml")]
bad = 0
for f in files:
    errors = sorted(jsonschema.validators.validator_for(schema)(schema).iter_errors(yaml.safe_load(Path(f).read_text())),
                    key=lambda e: list(e.path))
    print(f"{f}: {'OK' if not errors else f'{len(errors)} error(s)'}")
    for e in errors:
        print("  ", list(e.path), e.message[:160])
    bad += bool(errors)
sys.exit(1 if bad else 0)
