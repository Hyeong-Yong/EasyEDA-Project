"""Verify report/CSV/ZIP/database artifacts and exact staged Git bytes."""
from pathlib import Path
from html.parser import HTMLParser
import csv,hashlib,json,sqlite3,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/standard-values-20261019'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.links.extend(v for k,v in attrs if k=='href')
p=Links();p.feed((OUT/'index.html').read_text(encoding='utf8'))
for u in p.links:
    if not u.startswith(('https://','http://','#')):assert (OUT/u).is_file(),u
def csvrows(name):return list(csv.DictReader((OUT/name).open(encoding='utf-8-sig',newline='')))
bom,cpl=csvrows('BOM_CANDIDATE_REVIEW_ONLY.csv'),csvrows('CPL_CANDIDATE_REVIEW_ONLY.csv')
assert len(bom)==len(cpl)==412 and {r['Designator'] for r in bom}=={r['Designator'] for r in cpl}
assert all(r['Manufacturer Part'] for r in bom) and sum(float(r['Quantity']) for r in bom)==412
for name in ['STANDARD_VALUES_REVIEW.xlsx','native/final/GERBER_REVIEW_NOT_FOR_ORDER.zip']:
    with zipfile.ZipFile(OUT/name) as z:assert z.testzip() is None
native=ROOT/'native-project/STM32H747_MCU_BOARD_v19.eprj2'
con=sqlite3.connect(native.as_uri()+'?mode=ro',uri=True);assert con.execute('pragma quick_check').fetchall()==[('ok',)];con.close()
manifest_path=OUT/'PUBLISH_MANIFEST.json'
if '--manifest' in sys.argv:
    paths=sorted(set(x for x in git('ls-files','--cached','--others','--exclude-standard','-z','--','output/standard-values-20261019').decode().split('\0') if x and not x.endswith('PUBLISH_MANIFEST.json')))
    items=[{'path':x,'bytes':(ROOT/x).stat().st_size,'sha256':sha(ROOT/x)} for x in paths]
    m={'date':'2026-10-19','scope':'STM32 standard-resistor review; NOT manufacturing release','nativeProject':{'path':native.relative_to(ROOT).as_posix(),'bytes':native.stat().st_size,'sha256':sha(native)},'artifacts':items,'doesNotHashItself':True,'ignoredLocalEvidence':'Downloaded HTML, intermediate native source captures, parser copies and non-final export attempts stay local.'}
    manifest_path.write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf8')
m=json.loads(manifest_path.read_text(encoding='utf8'))
for item in [m['nativeProject'],*m['artifacts']]:
    f=ROOT/item['path'];assert sha(f)==item['sha256'] and f.stat().st_size==item['bytes'],item['path']
if '--staged' in sys.argv:
    staged=[x for x in git('diff','--cached','--name-only','-z').decode().split('\0') if x]
    assert staged and all(x.startswith('STM32H747 board/') for x in staged)
    for item in [m['nativeProject'],*m['artifacts']]:
        proc=subprocess.Popen(['git','cat-file','blob',':STM32H747 board/'+item['path']],cwd=ROOT,stdout=subprocess.PIPE)
        h=hashlib.sha256();size=0
        while chunk:=proc.stdout.read(1024*1024):h.update(chunk);size+=len(chunk)
        assert proc.wait()==0 and size==item['bytes'] and h.hexdigest()==item['sha256'],item['path']
print(json.dumps({'reportLinks':len(p.links),'bomCplParts':412,'zipAndDatabaseChecks':'PASS','manifestArtifacts':len(m['artifacts']),'stagedBytesVerified':'--staged' in sys.argv}))
