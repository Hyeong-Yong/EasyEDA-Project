"""Preserve the user's Apply result and compare it with the routed checkpoint."""
import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "output/pcb-two-zone"
backup = root / "backups/DAC8562 module_after_user_Apply_2026-10-12.eprj2"
if not backup.exists():
    with sqlite3.connect((root / "DAC8562 module.eprj2").resolve().as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(backup) as dst:
            src.backup(dst)
spec = importlib.util.spec_from_file_location("cio", root / "scripts/correction-io.py")
io = importlib.util.module_from_spec(spec)
spec.loader.exec_module(io)
before = io.documents(json.loads((out / "native-final-validation.json").read_text(encoding="utf8"))["source"])["4e08f91f9a2c4fe4"]
after = io.documents(json.loads((out / "after-apply-native-state.json").read_text(encoding="utf8"))["source"])["4e08f91f9a2c4fe4"]
changes = {}
for key in set(before["records"]) | set(after["records"]):
    a = before["records"].get(key, (None, None))[1]
    b = after["records"].get(key, (None, None))[1]
    if a != b:
        changes.setdefault(key[0], []).append({"id": key[1], "before": a, "after": b})
counts = lambda doc: dict(Counter(k[0] for k in doc["records"]))
result = {"backup": str(backup), "beforeCounts": counts(before), "afterCounts": counts(after), "changesByType": {k: len(v) for k, v in changes.items()}, "changes": changes}
(out / "after-apply-change-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
print(json.dumps({k: v for k, v in result.items() if k != "changes"}, indent=2))
