import json,re,sys
from pathlib import Path
out=Path(__file__).resolve().parents[1]/'output/pcb-two-zone'
def parse(text):
    comps={};nets={}
    for block in re.findall(r'\[\s*\n(.*?)\n\]',text,re.S):
        a=block.splitlines();attrs=dict(zip(a[::2],a[1::2]));comps[attrs.get('DESIGNATOR','')]=attrs
    for block in re.findall(r'\(\s*\n(.*?)\n\)',text,re.S):
        a=block.splitlines();nets[a[0].strip()]=sorted(re.sub(r'^([^-]+)-([^ ]+).*',r'\1.\2',s.strip()) for s in a[1:] if s.strip())
    return comps,nets
sc_path=Path(sys.argv[1]) if len(sys.argv)>1 else out.parent/'schematic-correction/erc-final-validation.json'
pcb_path=Path(sys.argv[2]) if len(sys.argv)>2 else out/'pcb-native-netlist.json'
result_path=Path(sys.argv[3]) if len(sys.argv)>3 else out/'protel-comparison.json'
sc=parse(json.loads(sc_path.read_text(encoding='utf8'))['pages'][-1]['netlist'])
pcb=parse(json.loads(pcb_path.read_text(encoding='utf8'))['netlist'])
comp_diff={}
for name in sorted(set(sc[0])|set(pcb[0])):
    a,b=sc[0].get(name,{}),pcb[0].get(name,{})
    dif={k:[a.get(k),b.get(k)] for k in set(a)|set(b) if a.get(k)!=b.get(k)}
    if dif:comp_diff[name]=dif
net_diff={n:[sc[1].get(n),pcb[1].get(n)] for n in set(sc[1])|set(pcb[1]) if sc[1].get(n)!=pcb[1].get(n)}
result={'counts':{'schematicComponents':len(sc[0]),'pcbComponents':len(pcb[0]),'schematicNets':len(sc[1]),'pcbNets':len(pcb[1])},'netDifferences':net_diff,'componentDifferences':comp_diff}
result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'counts':result['counts'],'netDifferences':net_diff,'componentMetadataDifferenceCount':len(comp_diff)},ensure_ascii=False,indent=2))
