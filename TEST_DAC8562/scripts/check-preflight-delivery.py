"""Read-only local-link/hash/model evidence checks; permits explicitly held CAD."""
import hashlib,json,sqlite3,zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
read=lambda p:json.loads(p.read_text(encoding='utf8'))
class Links(HTMLParser):
 def __init__(self):super().__init__();self.links=[]
 def handle_starttag(self,tag,attrs):
  self.links += [v for k,v in attrs if k in ('href','src') and v]
for p in (out/'preflight-report.html',out/'BOM-confirmed.html'):
 links=Links();links.feed(p.read_text(encoding='utf8'))
 for u in links.links:
  if not u.startswith(('http:','https:','#')):assert (p.parent/unquote(u)).exists(),(p,u)
proof=read(out/'checkpoint-proof.json')
for filename,key in ((proof['nativeCheckpoint'],'sha256'),(proof['portableCheckpoint'],'portableSha256')):
 assert hashlib.sha256((out/filename).read_bytes()).hexdigest()==proof[key]
for p in (root/'DAC8562 module.eprj2',out/proof['nativeCheckpoint']):
 with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
review=read(out/'review-summary.json');assert not review['fabricationReleased'] and review['schematicGlobalWarnings']==1 and review['pcbNetlistErrors']==1
assert read(out/'preflight-audit.json')['protectedR102PayloadsUnchanged']
assert read(out/'BOM-confirmed.json')['physicalPartCount']==154
with zipfile.ZipFile(out/'DFM_REFERENCE_ONLY_NOT_FOR_FABRICATION.zip') as z:
 assert 'FABRICATION HOLD' in z.read('READ_BEFORE_FABRICATION.txt').decode()
print('Report links, checkpoint hashes, SQLite integrity, protected R102 and explicit fabrication holds verified.')
