"""Create a consistent, non-overwriting backup before schematic layout edits."""
import hashlib
import json
import sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[1]
target=root/'backups/DAC8562 module_before_readability_2026-10-12.eprj2'
if target.exists():raise FileExistsError(target)
with sqlite3.connect((root/'DAC8562 module.eprj2').resolve().as_uri()+'?mode=ro',uri=True) as src:
    with sqlite3.connect(target) as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print(json.dumps({'backup':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
