"""Verify actual ECO identities/protected geometry before any placement."""
import json
import runpy
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'independent-pcb-placement-proposal.py'))


def main():
    before, after = M['parse'](M['BASELINE_SOURCE']), M['parse'](M['SOURCE'])
    ba, aa = M['attrs_of'](before), M['attrs_of'](after)
    br = {a['Designator']: cid for cid,a in ba.items() if 'Designator' in a}
    ar = {a['Designator']: cid for cid,a in aa.items() if 'Designator' in a}
    docs,_ = M['READ'](M['CHECK'])
    def holes(rows, attrs, refs):
        out = {}
        for ref,cid in refs.items():
            b = rows['COMPONENT',cid]
            hh = []
            for (k,rid),(_,p) in docs['FOOTPRINT',attrs[cid]['Footprint']].items():
                if k=='PAD' and p.get('hole'):
                    hh.append({'pad':str(p['num']),'localCenter':[p['centerX'],p['centerY']],'padAngle':p.get('padAngle',0),'hole':p['hole'],'plated':p.get('plated')})
            if hh: out[ref]={'componentXY':[b['x'],b['y']],'angle':b['angle'],'layerId':b['layerId'],'holes':sorted(hh,key=lambda p:p['pad'])}
        return out
    old_holes,new_holes=holes(before,ba,br),holes(after,aa,ar)
    preserved=[]
    for kind in ('VIA','PAD','LINE','ARC','FILL','POLY','STRING','RULE','LAYER','LAYER_PHYS'):
        b={k:v for k,v in before.items() if k[0]==kind}
        a={k:v for k,v in after.items() if k[0]==kind}
        preserved.append({'kind':kind,'beforeCount':len(b),'afterCount':len(a),'exactlyEqual':b==a,'missing':[list(k) for k in b.keys()-a.keys()],'added':[list(k) for k in a.keys()-b.keys()],'changed':[list(k) for k in b.keys()&a.keys() if b[k]!=a[k]]})
    uid_diff=[]
    for ref,cid in br.items():
        actual=after['COMPONENT',ar[ref]]['attrs'].get('Unique ID') if ref in ar else None
        if before['COMPONENT',cid]['attrs'].get('Unique ID')!=actual:uid_diff.append(ref)
    hole_count=sum(len(x['holes']) for x in new_holes.values())
    via_count=sum(k[0]=='VIA' for k in after)
    board_holes=sum(k[0]=='PAD' and bool(v.get('hole')) for k,v in after.items())
    placement=HERE/'independent-pcb-placement-rebased-eco-proposal.json'
    p=json.loads(placement.read_text(encoding='utf8'))
    checks={
        'all354OriginalPhysicalUIDsPreserved':len(br)==354 and not uid_diff,
        'exactly83NewPhysicalParts437Total':len(ar)==437 and len(ar.keys()-br.keys())==83,
        'allProtectedCopperOutlineSilkRulesAndLayersExactlyEqual':all(x['exactlyEqual'] for x in preserved),
        'allOriginalComponentHoleRecordsIdenticalNoNewComponentHoles':old_holes==new_holes,
        'actual640ViasAnd799PhysicalDrills':via_count==640 and via_count+board_holes+hole_count==799,
        'placementProposalRebasedToActualEco':p['sourceSha256']==M['sha'](M['SOURCE']),
        '83NewAnd24ExistingPlacementEntriesComplete':p['newPartsProposed']==83 and len(p['existingPartsRelocatedProposed'])==24 and not p['failedSearches'],
        'all107ProposedPadNetBindingsVerified':len(p['edits'])==107 and all(x['actualPadNetContractVerified'] for x in p['edits']),
    }
    r={'schema':'adc10-labtool-independent-pcb-eco-placement-scope-audit-20261018-v1','status':'PASS' if all(checks.values()) else 'FAIL','sourcePath':str(M['SOURCE']),'sourceSha256':M['sha'](M['SOURCE']),'beforePath':str(M['BASELINE_SOURCE']),'beforeSha256':M['sha'](M['BASELINE_SOURCE']),'placementPath':str(placement),'placementSha256':M['sha'](placement),'checks':checks,'protectedTypes':preserved,'originalUIDDifferences':uid_diff,'physicalDrills':{'vias':via_count,'standaloneBoardHoles':board_holes,'componentHoles':hole_count,'total':via_count+board_holes+hole_count},'componentHoleInventory':new_holes,'nativeCalls':0,'designModified':False,'manufacturingApproved':False,'qualification':'This is an actual preplacement ECO preservation audit, not proof that prospective placement/routing is electrically connected or DRC-clean.'}
    out=HERE/'independent-pcb-eco-placement-scope-audit.json'
    out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'path':str(out),'sha256':M['sha'](out),'status':r['status'],'checks':checks,'drills':r['physicalDrills']},ensure_ascii=False))


if __name__=='__main__':main()
