"""Plan native Net restoration only; preserve R102 protected connection exactly."""
import importlib.util,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
old=json.loads((root/'output/readability/native-validation.json').read_text(encoding='utf8'))
wires=json.loads((out/'wires-before.json').read_text(encoding='utf8'))
plan=[]
for pg in wires['pages']:
 d=next(iter(io.documents(next(p for p in old['pages'] if p['page']==pg['page'])['source']).values()));aa=io.attrs(d)
 edits=[{'id':w['id'],'net':aa.get(w['id'],{}).get('NET')} for w in pg['wires'] if not w['net'] and aa.get(w['id'],{}).get('NET') and w['id']!='2499435c58e74be8']
 plan.append({'page':pg['page'],'edits':edits})
(out/'net-restoration-plan.json').write_text(json.dumps(plan,indent=2),encoding='utf8')
code='const pages=[];for(const pg of '+json.dumps(plan)+'){await eda.dmt_EditorControl.openDocument(pg.page);const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!==pg.page)throw new Error("Wrong page");const wires=await eda.sch_PrimitiveWire.getAll();for(const e of pg.edits){const w=wires.find(w=>w.getState_PrimitiveId()===e.id);if(!w)throw new Error("Missing wire "+e.id);const edit=w.toAsync();edit.setState_Net(e.net);await edit.done();}if(!await eda.sch_Document.save())throw new Error("Save failed");pages.push({page:pg.page,editCount:pg.edits.length,details:await eda.sch_Drc.check(true,true,true),source:await eda.sys_FileManager.getDocumentSource(),netlist:await eda.sch_Netlist.getNetlist("Protel2")});}return {pages};'
(out/'restore-nets-native.js').write_text(code,encoding='utf8')
print(json.dumps(plan,indent=2))
