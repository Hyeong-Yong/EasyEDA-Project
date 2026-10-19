"""Derive a two-part pumpoutput loop refinement, plus exact actualV3 guard.
Does not write anynativefile or touch priorfrozenv2/v3artifacts.
"""
import contextlib,copy,hashlib,io,json,math,runpy
from pathlib import Path
HERE=Path(__file__).resolve().parent
generator=HERE/'independent-commonpower-placement-variant.py'
code=generator.read_text(encoding='utf8')
old="CHANGES={'U30':((31.0,29.8),0),'U31':((38.0,29.8),0),'C150':((27.7,29.8),90),'R197':((27.7,33.6),270),'C151':((31.0,26.8),180),'C152':((34.7,29.8),90),'C153':((41.5,30.0),90),'D20':((30.8,33.2),180)}"
assert old in code
code=code.replace(old,"CHANGES={'C152':((31.0,33.6),270),'D20':((34.2,33.2),180)}")
code=code.replace("BASE=HERE/'independent-pcb-placement-short-negative-variant-v2.json'","BASE=HERE/'independent-pcb-placement-short-negative-commonpower-v3-proposal.json'")
code=code.replace("OUT=HERE/'independent-pcb-placement-short-negative-commonpower-v3-proposal.json'","OUT=HERE/'independent-pcb-placement-short-negative-commonpower-v4-proposal.json'")
code=code.replace('6c28f76d936bfb004411455abab9127ba88e4004ce3ed5aae2defc66b8fed51f','f5b57e6a6b7b0e551873f1ea92d129b222ccc7d800637d12889b6dde992d8eff')
code=code.replace("if __name__=='__main__':main()",'')
env={'__file__':str(generator),'__name__':'commonpower_v4_derived'}
exec(compile(code,str(generator),'exec'),env)
with contextlib.redirect_stdout(io.StringIO()):env['main']()
H=env['H'];MM=H['MM'];out=env['OUT'];p=json.loads(out.read_text(encoding='utf8'))
p['schema']='adc10-labtool-placement-shortnegative-commonpower-v4-proposal'
p['status']='OFFLINE_2PART_COMMONPOWER_OUTPUTLOOP_REFINEMENT_REVIEWED_PENDING_NATIVE'
p['v4ParentPath']=p.pop('v3ParentPath');p['v4ParentSha256']=p.pop('v3ParentSha256')
p['v4OnlyChangedRefs']=p.pop('v3OnlyChangedRefs');p['v4Checks']=p.pop('v3Checks')
p['v4Checks']['other105EditsExactV3']=p['v4Checks'].pop('other99EditsExactV2')
p['v4Tradeoff']='C152nowprioritizeschargepumpOUTpulsedcurrentloop(~2.302mmcentrelead); LDOINfeedbecomes~7mm, lowerloadbutunmeasuredstartup/ripple/stability remainsunqualified. NoSC/net/partcountchange.'
out.write_text(json.dumps(p,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
actual=H['ROOT']/'output/validation/native-adc10-pcb-labtool_place_5-20261018.epru'
assert H['sha'](actual)=='6e30bca25f0745c32a8954653c0ce593f93bdca978b3ead54aca490c524b9665'
rows=H['parse'](actual);ops=[]
for q in p['edits']:
    if q['ref'] not in ('C152','D20'):continue
    cid=q['componentId'];b=rows['COMPONENT',cid];a=copy.deepcopy(b)
    a.update(x=round(q['set']['x'],4),y=round(q['set']['y'],4),angle=q['angle'])
    owned=[];ang=math.radians(q['angle']-b['angle']);c,s=math.cos(ang),math.sin(ang)
    for (k,r),ab in rows.items():
        if k!='ATTR' or ab.get('parentId')!=cid:continue
        aa=copy.deepcopy(ab)
        if aa.get('x') is not None and aa.get('y') is not None:
            dx,dy=ab['x']-b['x'],ab['y']-b['y']
            aa['x']=round(q['set']['x']+c*dx-s*dy,4);aa['y']=round(q['set']['y']+s*dx+c*dy,4)
        aa['angle']=(ab.get('angle',0)+q['angle']-b['angle'])%360
        owned.append({'type':'ATTR','id':r,'beforeBody':ab,'expectedAfterRound4Mil':aa})
    ops.append({'ref':q['ref'],'type':'COMPONENT','id':cid,'beforeBody':b,'set':q['set'],'expectedAfterRound4Mil':a,'ownedAttrs':owned,'allowedComponentChangedFields':['x','y','angle'],'actualPadContract':q['pads']})
manifest={'schema':'labtool-commonpower-v4-two-components-actual-native-guard','status':'OFFLINE_PUBLIC_API_OPERATIONS_ROOT_REVIEW_REQUIRED','sourcePath':str(actual),'sourceSha256':H['sha'](actual),'placementPath':str(out),'placementSha256':H['sha'](out),'nativeCalls':0,'operations':ops,'protectedContract':['Only2COMPONENTxy/rotation andtheir6ownedATTRxy/anglemaychange.','All437UID/PAD_NETcontracts/640VIA/799drills/6layers/18rules/oldCu bodiesunchanged.','Expectedcoordinatequantization is4decimalsMIL; exactpublicAPIattrplacementmustbeverifiedafteractualcapture, notassumedfromthisproposal.']}
mp=HERE/'routing/commonpower-v4-two-component-actual-operations.json';mp.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
print(json.dumps({'placement':str(out),'sha256':H['sha'](out),'manifest':str(mp),'manifestSha256':H['sha'](mp),'count':len(ops)}))
