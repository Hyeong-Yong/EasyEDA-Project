"""Resolve native library UUIDs from exact title/source and audit preservation."""
import copy
import hashlib
import json
import runpy
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/candidates/adc10-labtool-20261018/libraries'
READ=runpy.run_path(str(ROOT/'output/candidates/adc10-dc-buffer-20261017/build-adc10-dc-candidate.py'))['read_checkpoint']


def main():
    protection='--protection' in sys.argv
    out=OUT/'reverse-protection' if protection else OUT
    before=READ(ROOT/('output/checkpoints/STM32H747_labtool_adc_page_wip_20261018.epro2' if protection else 'output/checkpoints/STM32H747_before_labtool_afe_20261018.epro2'))
    checkpoint=ROOT/('output/checkpoints/STM32H747_labtool_protection_libraries_20261018.epro2' if protection else 'output/checkpoints/STM32H747_labtool_libraries_20261018.epro2')
    after=READ(checkpoint)
    manifest=json.loads((out/('reverse-protection-library-manifest.json' if protection else 'adc10-labtool-library-manifest.json')).read_text())
    new=set(after)-set(before)
    result={'schema':'adc10-labtool-runtime-library-map-20261018-v1','devices':{},'symbols':{},'footprints':{}}
    mapping={}
    matched=set()
    for group,kind in [('symbols','SYMBOL'),('footprints','FOOTPRINT'),('devices','DEVICE')]:
        for name,original in manifest[group].items():
            hits=[]
            for key in new:
                if key[0]!=kind:continue
                meta=next((b for h,b in after[key].values() if h['type']=='META'),{})
                if meta.get('title')==original['title'] or str(meta.get('source','')).split('|')[0]==original['uuid']:
                    hits.append((key,meta))
            if len(hits)!=1:raise RuntimeError(('ambiguous library',group,name,hits))
            key,meta=hits[0]; matched.add(key)
            mapped=copy.deepcopy(original)
            mapped.update(uuid=key[1],oldUuid=original['uuid'],source=meta.get('source',''),runtimeMeta=meta)
            result[group][name]=mapped;mapping[original['uuid']]=key[1]
    for device in result['devices'].values():
        for field in ('symbolUuid','footprintUuid'):device[field]=mapping[device[field]]
        device['attributes']['Symbol']=device['symbolUuid'];device['attributes']['Footprint']=device['footprintUuid']
    if matched!=new or len(new)!=(3 if protection else 14):raise RuntimeError(('unexpected documents',new-matched,len(new)))
    changes=[];ignore={'DOCHEAD','CANVAS','ACTIVE_LAYER','ELE_PLACEHOLDER'}
    for doc,rows in before.items():
        if doc not in after:raise RuntimeError(('missing document',doc))
        for key in rows.keys()|after[doc].keys():
            if key[0] in ignore:continue
            a=rows.get(key);b=after[doc].get(key)
            if (a[1] if a else None)!=(b[1] if b else None):changes.append([*doc,*key])
    if changes:raise RuntimeError(('preexisting library/design changed',changes))
    result.update(uuidMap=mapping,checkpoint=str(checkpoint),checkpointSha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())
    (out/'runtime-library-map.json').write_text(json.dumps(result,indent=2)+'\n')
    audit={'passed':True,'newOnlyDocumentCount':len(new),'counts':dict(Counter(k[0] for k in new)),'preexistingDocumentsPreserved':len(before),'nonBookkeepingChanges':changes,'schematicAndPcbUnchanged':True}
    (out/'native-import-preservation-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps(audit))


if __name__=='__main__':main()
