"""Connect only R102.1 to the existing MCU_RECEIVE_A wire, with a real T node."""
import copy,hashlib,importlib.util,json,sqlite3,uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/r102-connection-fix'
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
backup=root/'backups/DAC8562_before_R102_connection_fix_2026-10-13.eprj2'
if backup.exists():raise FileExistsError(backup)
with sqlite3.connect((root/'DAC8562 module.eprj2').resolve().as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(backup) as dst:
  src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
capture=json.loads((out/'before-native.json').read_text(encoding='utf8'));pg=next(p for p in capture['pages'] if p['page']=='e3a1c5f417017755')
doc=next(iter(io.documents(pg['source']).values()));before=copy.deepcopy(doc);attrs=io.attrs(doc)
branch='2499435c58e74be8';receiver='13478fd0989e44f0';hline=('LINE','ebc43c3410044772');vline=('LINE','ad2fc6e173fa4f13')
assert attrs[receiver]['NET']=='MCU_RECEIVE_A' and not attrs[branch].get('NET')
assert doc['records'][hline][1]['startX']==440 and doc['records'][hline][1]['endX']==530
assert doc['records'][vline][1]['startX']==490 and doc['records'][vline][1]['startY']==-1820
clock=max(h.get('ticket',0) for h,p in doc['records'].values())+100
def update(key,p):
 global clock
 clock+=1;h=dict(doc['records'][key][0]);h['ticket']=clock;doc['records'][key]=(h,p)
vp=copy.deepcopy(doc['records'][vline][1]);vp['lineGroup']=receiver;update(vline,vp)
hp=copy.deepcopy(doc['records'][hline][1]);right=copy.deepcopy(hp);hp['endX']=490;right['startX']=490;update(hline,hp)
clock+=1;newid=uuid.uuid4().hex[:16];doc['records'][('LINE',newid)]=({'type':'LINE','id':newid,'ticket':clock},right)
removed=[k for k,(_,p) in doc['records'].items() if k==('WIRE',branch) or p.get('parentId')==branch]
for key in removed:del doc['records'][key]
allowed=set(removed)|{hline,vline,('LINE',newid)}
for key in set(before['records'])|set(doc['records']):
 a=before['records'].get(key,(None,None))[1];b=doc['records'].get(key,(None,None))[1]
 if a!=b:assert key in allowed,('Unrelated edit',key)
target=out/'DAC_MCU.R102-connected-source.txt';target.write_text(io.source_of(doc),encoding='utf8')
proof={'backup':str(backup),'backupSha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'page':'DAC_MCU','change':'R102.1: singleton $2N434 -> MCU_RECEIVE_A','junction':{'x':490,'y':-1820,'sharedWireParent':receiver,'horizontalWireSplitAtT':True},'unchanged':'All component/part/BOM attributes, R102 value, lower MCU_VBIAS wire, unrelated wiring and all PCB copper.','removedUnconnectedBranchRecords':[list(k) for k in removed],'changedLineIds':[hline[1],vline[1],newid]}
(out/'change-plan.json').write_text(json.dumps(proof,indent=2),encoding='utf8');print(json.dumps(proof,indent=2))
