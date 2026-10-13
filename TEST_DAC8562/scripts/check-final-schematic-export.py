"""Check actual saved native pages and portable export, not just generation inputs."""
import importlib.util,json,sys
from collections import defaultdict
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('auditor',root/'scripts/audit-readable-schematics.py')
a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
sys.path.insert(0,str(root/'.tools/pcb-python'))
from shapely.geometry import LineString
from shapely.ops import unary_union
capture=json.loads((root/'output/readability/native-validation.json').read_text(encoding='utf8'))
export=a.io.read_export(root/'output/final-review/DAC8562 module_final_review_ERC_DRC_clean.epro2')
expected=json.loads((root/'output/readability/source-audit.json').read_text(encoding='utf8'))['pinNets']
result=[]
def wire_geometry(d):
    groups=defaultdict(list)
    for (t,i),(_,p) in d['records'].items():
        if t=='LINE' and p.get('lineGroup') and ('WIRE',p['lineGroup']) in d['records']:
            coords=[(round(p['startX'],6),round(p['startY'],6)),(round(p['endX'],6),round(p['endY'],6))]
            if coords[0]!=coords[1]:groups[p['lineGroup']].append(LineString(coords))
    return {k:unary_union(v) for k,v in groups.items()}
for pg in capture['pages']:
    live=next(iter(a.io.documents(pg['source']).values()));portable=export[pg['page']]
    lp,ls=a.graph(live);ep,es=a.graph(portable)
    assert not ls and not es,(ls,es)
    assert lp==ep
    assert all(expected[k]==v for k,v in lp.items())
    la,ea=a.io.attrs(live),a.io.attrs(portable)
    assert la==ea,'Exported schematic values / part properties changed'
    lw,ew=wire_geometry(live),wire_geometry(portable)
    diffs=[k for k in set(lw)|set(ew) if k not in lw or k not in ew or not lw[k].equals(ew[k])]
    assert not diffs,('Wire geometry differs',diffs)
    result.append({'page':pg['page'],'passed':True,'pinNetCount':len(lp),
                   'wireGeometryAndPartPropertiesIdentical':True,
                   'exportNormalization':'Native export retains historical orphan LINE records whose WIRE parents no longer exist, and normalizes text rendering metadata / floating point; all live wire geometry, attributes and pin nets match.'})
report={'passed':True,'pages':result}
(root/'output/final-review/schematic-export-audit.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report,indent=2))
