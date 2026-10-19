import hashlib, sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[1]
dest=root/'output/schematic-correction/DAC8562 module_schematic_ERC_clean.eprj2'
if dest.exists(): raise FileExistsError(dest)
with sqlite3.connect((root/'DAC8562 module.eprj2').resolve().as_uri()+'?mode=ro',uri=True) as src:
    with sqlite3.connect(dest) as dst: src.backup(dst)
print(dest)
print(hashlib.sha256(dest.read_bytes()).hexdigest())
