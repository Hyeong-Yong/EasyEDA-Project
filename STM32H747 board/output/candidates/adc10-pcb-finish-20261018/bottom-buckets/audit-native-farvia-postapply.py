"""Read-only native realization audit of frozen remaining-six operations."""
import hashlib
import json
import math
import runpy
import sys
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'plan-bottom-buckets.py'))
MANIFEST=HERE/'remaining6-native-operations-c95-farvia-20261018.json'
EXPECTED_MANIFEST='60735a1709cdb441f51c99bbcf4d139a76bcce569176408e6851ebf6044e2780'
assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest()==EXPECTED_MANIFEST

def sha(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def rounded_xy(xy):return tuple(round(v,4) for v in xy)
def linekey(v):return (v['netName'],v['layerId'],tuple(sorted((rounded_xy([v['startX'],v['startY']]),rounded_xy([v['endX'],v['endY']])))),round(v['width'],4))

def main():
    source=M['ROOT']/'output/validation'/sys.argv[1]
    source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    if len(sys.argv)>2:assert source_sha==sys.argv[2]
    d=json.loads(MANIFEST.read_text());before=M['OLD']['PARSE'](Path(d['sourcePath']));after=M['OLD']['PARSE'](source)
    new={k:v for k,v in after.items() if k not in before};missing=[k for k in before if k not in after]
    assert not missing,missing
    old_vias={k:v for k,v in before.items() if k[0]=='VIA'}
    assert len(old_vias)==634
    assert all(after[k]==v for k,v in old_vias.items())
    new_vias={k:v for k,v in new.items() if k[0]=='VIA'};new_lines={k:v for k,v in new.items() if k[0]=='LINE'}
    assert len(new_vias)==6,len(new_vias)
    assert len(new_lines)==31,len(new_lines)
    expected_vias=Counter((v['net'],rounded_xy(v['xyMil']),round(v['holeDiameterMil'],4),round(v['diameterMil'],4)) for v in d['viaCreates'])
    realized_vias=Counter((v['netName'],rounded_xy([v['centerX'],v['centerY']]),round(v['holeDiameter'],4),round(v['viaDiameter'],4)) for v in new_vias.values())
    assert realized_vias==expected_vias,(realized_vias-expected_vias,expected_vias-realized_vias)
    expected_lines=Counter((v['net'],v['layerId'],tuple(sorted((rounded_xy(v['startXYmil']),rounded_xy(v['endXYmil'])))),round(v['widthMil'],4)) for v in d['lineCreates'])
    realized_lines=Counter(linekey(v) for v in new_lines.values())
    assert realized_lines==expected_lines,(realized_lines-expected_lines,expected_lines-realized_lines)
    assert all(v['viaType']=='NORMAL' and v.get('unusedInnerLayers',[])==[] for v in new_vias.values())
    direct4=json.loads((HERE/'direct4-native-operations-ready-for-calibration.json').read_text())
    expected_components={m['ref']:m for m in direct4['componentMoves']}
    expected_components.update({m['ref']:m for m in d['alreadyAppliedRemaining6ComponentMoves']})
    assert len(expected_components)==10
    docs,_=M['READ'](M['CHECKPOINT']);attrs={};padnets={}
    for (k,i),v in after.items():
        if k=='ATTR':attrs.setdefault(v['parentId'],{})[v['key']]=v.get('value')
        elif k=='PAD_NET':
            a=json.loads(i);padnets[a[1],str(a[2])]=v['padNet']
    pad_audit=[]
    for ref,move in expected_components.items():
        cid=move['primitiveId'];c=after['COMPONENT',cid];t=math.radians(c['angle']);pads=[]
        assert c['layerId']==move['targetLayerId']
        for (pk,pid),(h,p) in docs['FOOTPRINT',attrs[cid]['Footprint']].items():
            if pk!='PAD':continue
            xy=[(c['x']+p['centerX']*math.cos(t)-p['centerY']*math.sin(t))*M['MM'],(c['y']+p['centerX']*math.sin(t)+p['centerY']*math.cos(t))*M['MM']]
            expected=move['requiredWorldPadsMm'][str(p['num'])]
            assert padnets[cid,str(p['num'])]==expected['net']
            error=math.dist(xy,expected['xyMm']);assert error<.000003,(ref,p['num'],xy,expected)
            physical_layer=3-p['layerId'] if c['layerId']==2 and p['layerId'] in [1,2] else p['layerId']
            assert physical_layer==move['targetLayerId']
            pads.append({'pin':str(p['num']),'layerId':physical_layer,'actualXYmm':xy,'requiredXYmm':expected['xyMm'],'errorMm':error})
        pad_audit.append({'ref':ref,'nativeAngleDegrees':c['angle'],'layerId':c['layerId'],'pads':pads,'passed':True})
    M['Board'].__init__.__globals__['SOURCE']=source;b=M['Board']()
    for k in new_vias:del b.rows[k]
    proposals=[{'ref':p['ref'],'xyMm':[x*M['MM'] for x in p['xyMil']],'holeMm':p['holeDiameterMil']*M['MM']} for p in d['viaCreates']]
    drill_audit=runpy.run_path(str(HERE/'audit-full-original-drills.py'))['audit'](M,b,proposals)
    assert drill_audit['inventorySha256']==d['all793OriginalPhysicalHoleClearanceAudit']['inventorySha256']
    out={'schema':'adc10-native-farvia-postapply-realization-audit-20261018-v1','sourcePath':str(source),'sourceSha256':source_sha,'frozenManifestSha256':EXPECTED_MANIFEST,'passed':True,'nativeCallsPerformed':False,'allOriginal634ViaBodiesExact':True,'allOriginal793PhysicalDrillsExact':True,'new6ViasMatchAtNative4DecimalMil':True,'new31LinesMatchAtNative4DecimalMil':True,'finalViaCount':634+len(new_vias),'finalPhysicalDrillCount':793+len(new_vias),'newViaIds':[k[1] for k in new_vias],'newLineIds':[k[1] for k in new_lines],'all10CapacitorNativeWorldPadAudit':pad_audit,'original793InventorySha256':drill_audit['inventorySha256'],'strictNativeDrcStillRequired':True,'scope':'Realization/preservation of six VIAs,31 LINEs,20 capacitor worldpads,634 old VIA bodies and793 old physicaldrills; final FILL topology/all44GND connectivity/nativeDRC and CAM audited separately.'}
    target=HERE/'native-farvia-postapply-realization-audit-20261018.json';target.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'passed':True,'newVias':len(new_vias),'newLines':len(new_lines),'nativeWorldPads':sum(len(r['pads']) for r in pad_audit),'old793DrillsExact':True}))

if __name__=='__main__':main()
