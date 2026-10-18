"""Full-board original 793 physical hole inventory and proposed hole gaps."""
import hashlib
import json
import math
from collections import Counter

def audit(M,board,proposals):
    mm=M['MM'];docs,_=M['READ'](M['CHECKPOINT']);holes=[]
    for (k,i),v in board.rows.items():
        if k=='VIA':holes.append({'id':i,'kind':'via_round','xyMm':[v['centerX']*mm,v['centerY']*mm],'diameterMm':v['holeDiameter']*mm,'sourceBodySha256':hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
        elif k=='PAD' and v.get('hole'):
            h=v['hole'];dia=max(h.get('width',0),h.get('height',0))*mm
            if dia>0:holes.append({'id':i,'kind':'board_npth','xyMm':[v['centerX']*mm,v['centerY']*mm],'diameterMm':dia})
        elif k=='COMPONENT':
            t=math.radians(v['angle']);ct=math.cos(t);st=math.sin(t)
            for (pk,pid),(head,p) in docs['FOOTPRINT',board.attrs[i]['Footprint']].items():
                if pk!='PAD' or not p.get('hole'):continue
                h=p['hole'];dia=max(h.get('width',0),h.get('height',0))*mm
                if dia<=0:continue
                x,y=p['centerX']*mm,p['centerY']*mm
                typ='component_npth' if p.get('plated') is False else 'component_slot' if h.get('holeType')=='SLOT' else 'component_round'
                holes.append({'id':i+':'+pid,'ref':board.attrs[i]['Designator'],'kind':typ,'xyMm':[v['x']*mm+x*ct-y*st,v['y']*mm+x*st+y*ct],'diameterMm':dia,'holeGeometry':h,'diameterBoundIsConservativeForSlot':typ=='component_slot'})
    counts=dict(Counter(p['kind'] for p in holes))
    expected={'via_round':634,'board_npth':4,'component_round':133,'component_slot':13,'component_npth':9}
    assert counts==expected,(counts,expected)
    gaps=[]
    for p in proposals:
        distances=[(math.dist(p['xyMm'],q['xyMm'])-(p['holeMm']+q['diameterMm'])/2,q) for q in holes]
        gap,near=min(distances,key=lambda v:v[0])
        gaps.append({'ref':p['ref'],'xyMm':p['xyMm'],'minimumPhysicalHoleEdgeGapMm':gap,'nearestOldPhysicalHoleId':near['id'],'nearestOldPhysicalHoleKind':near['kind'],'requiredHoleEdgeGapMm':.2999994,'passed':gap>=.2999994})
    return {'originalPhysicalDrillCount':len(holes),'originalDrillKindCounts':counts,'inventorySha256':hashlib.sha256(json.dumps(holes,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'all793DrillsConsideredWithoutSpatialOmission':True,'slotMaxDimensionCircumscribedCircleUsedConservatively':True,'newVsOriginalDrillAudits':gaps,'allNewVsOriginalHoleEdgesPassed':all(g['passed'] for g in gaps),'proposedTotalPhysicalDrills':len(holes)+len(proposals),'originalDrillInventory':holes}
