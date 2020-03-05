import json
from pathlib import Path

pending = json.load(open("results/pending.json"))
assert len(pending) == 1
assert pending[0]["ip"] == "172.1.0.101"

registered = json.load(open("results/registration.json"))
assert len(registered) == 1
assert registered[0]["name"] == "bamboo-agent"
assert registered[0]["type"] == "REMOTE"
assert registered[0]["active"]
assert registered[0]["enabled"]

ansible_output = Path("results/ansible.out").read_text()
assert (
    "bamboo-agent               : ok=4    changed=3    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0"
    in ansible_output
)
