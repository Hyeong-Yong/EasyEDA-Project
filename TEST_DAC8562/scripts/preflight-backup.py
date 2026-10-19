import hashlib,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[1]
target=root/'backups/DAC8562_before_manufacturing_preflight_2026-10-13.eprj2'
if target.exists():raise FileExistsError(target)
with sqlite3.connect((root/'DAC8562 module.eprj2').resolve().as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(target) as dst:
  src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print(target,hashlib.sha256(target.read_bytes()).hexdigest())
