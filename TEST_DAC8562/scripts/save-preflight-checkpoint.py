"""Non-overwriting consistent SQLite backup; not an ERC/DFM-clean release."""
import hashlib,json,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
target=out/'DAC8562_review_checkpoint_R102_pending.eprj2'
if target.exists():raise FileExistsError(target)
with sqlite3.connect((root/'DAC8562 module.eprj2').resolve().as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(target) as dst:
  src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
proof={'nativeCheckpoint':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'integrityCheck':'ok','fabricationReleased':False,'portableCheckpoint':'DAC8562_review_checkpoint_R102_pending.epro2','portableSha256':hashlib.sha256((out/'DAC8562_review_checkpoint_R102_pending.epro2').read_bytes()).hexdigest()}
(out/'checkpoint-proof.json').write_text(json.dumps(proof,indent=2),encoding='utf8');print(json.dumps(proof,indent=2))
