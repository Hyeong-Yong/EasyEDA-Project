"""Read-only report-link, native-file integrity and artifact-hash checks."""
import hashlib,json,sqlite3
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
root=Path(__file__).resolve().parents[1];out=root/'output/final-review'
class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        for k,v in attrs:
            if k in ('href','src') and v:self.links.append(v)
for path in (out/'final-review.html',out/'BOM-reviewed.html'):
    parser=Links();parser.feed(path.read_text(encoding='utf8'))
    for u in parser.links:
        if u.startswith(('https:','http:','#')):continue
        assert (path.parent/unquote(u)).exists(),(path.name,u)
review=json.loads((out/'review-summary.json').read_text(encoding='utf8'))
assert review['schematicErcPassed'] and review['pcbNativeDrcPassed'] and not review['pcbNativeDrcDetails']
assert review['physicalCopperAuditPassed'] and review['analogSimulationPassed']
release=json.loads((out/'release-verification.json').read_text(encoding='utf8'))
target=out/'DAC8562 module_final_review_ERC_DRC_clean.eprj2'
for path in (root/'DAC8562 module.eprj2',target):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert hashlib.sha256(target.read_bytes()).hexdigest()==release['nativeFileSha256']
assert hashlib.sha256((out/release['portableProjectExport']).read_bytes()).hexdigest()==release['portableExportSha256']
print('Report local links OK; both native databases integral; release hashes exact; ERC/DRC/copper/simulation passed.')
