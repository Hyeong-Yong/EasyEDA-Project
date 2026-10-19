"""Non-overwriting consistent backup of the pending native ECO checkpoint."""
import hashlib,json,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[1]
target=root/'output/final-review/DAC8562 module_final_review_ECO_pending.eprj2'
if target.exists():raise FileExistsError(target)
with sqlite3.connect((root/'DAC8562 module.eprj2').resolve().as_uri()+'?mode=ro',uri=True) as src:
    with sqlite3.connect(target) as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print(json.dumps({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'release':'ECO pending, not final fabrication'},ensure_ascii=False))
