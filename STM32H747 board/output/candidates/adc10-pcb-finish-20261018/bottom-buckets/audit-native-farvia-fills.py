"""Read-only exact native four-decimal-mil polygon realization proof."""
import hashlib
import json
import runpy
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'plan-bottom-buckets.py'))
F=runpy.run_path(str(HERE/'build-local-fill-operations.py'))
MANIFEST=HERE/'remaining6-native-operations-c95-farvia-20261018.json'
EXPECTED='60735a1709cdb441f51c99bbcf4d139a76bcce569176408e6851ebf6044e2780'
assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest()==EXPECTED
def norm(v):
    if isinstance(v,(int,float)):return round(v,4)
    if isinstance(v,list):return [norm(x) for x in v]
    return v
def pathkey(path):return norm([F['closed_native'](p) for p in path])
def sha(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def main():
    source=M['ROOT']/'output/validation'/sys.argv[1];source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    if len(sys.argv)>2:assert source_sha==sys.argv[2]
    d=json.loads(MANIFEST.read_text());before=M['OLD']['PARSE'](Path(d['sourcePath']));after=M['OLD']['PARSE'](source)
    audit=[];errors=[]
    for o in d['fillModifyOperations']:
        fid=o['primitiveId'];v=after['FILL',fid];expected=pathkey(o['afterPathsExplicitlyClosedForApi']);actual=pathkey(v['path'])
        equal=actual==expected
        properties={k:[value,v.get(k)] for k,value in o['beforeBody'].items() if k not in ['path','refs'] and v.get(k)!=value}
        row={'id':fid,'operation':'modify','layerId':v['layerId'],'net':v['netName'],'exactFullPathAtNative4DecimalMil':equal,'expectedPathSha256':sha(expected),'actualPathSha256':sha(actual),'rings':len(v['path']),'allOtherFillFieldsPreservedExceptNativeRefsNormalization':not properties,'otherPropertyChanges':properties}
        audit.append(row)
        if not equal or properties:errors.append(row)
    newfills={i:v for (k,i),v in after.items() if k=='FILL' and (k,i) not in before}
    assert len(newfills)==len(d['fillCreateOperations'])==1
    for o in d['fillCreateOperations']:
        expected=pathkey(o['afterPathsExplicitlyClosedForApi']);matches=[(i,v) for i,v in newfills.items() if pathkey(v['path'])==expected]
        assert len(matches)==1,(o['semanticId'],list(newfills))
        fid,v=matches[0]
        equal=v['layerId']==o['layerId'] and v['netName']==o['net'] and round(v['width'],4)==round(o['lineWidthMil'],4)
        row={'id':fid,'operation':'create','semanticId':o['semanticId'],'layerId':v['layerId'],'net':v['netName'],'exactFullPathAtNative4DecimalMil':True,'allExpectedStyleAndNetFields':equal,'expectedPathSha256':sha(expected),'actualPathSha256':sha(pathkey(v['path'])),'rings':len(v['path'])};audit.append(row)
        if not equal:errors.append(row)
    geometry_pass=all(r['exactFullPathAtNative4DecimalMil'] for r in audit)
    metadata_changes=[{'id':r['id'],'changes':r['otherPropertyChanges']} for r in audit if r.get('otherPropertyChanges')]
    out={'schema':'adc10-native-farvia-exact13fills1lobe-audit-20261018-v1','sourcePath':str(source),'sourceSha256':source_sha,'frozenManifestSha256':EXPECTED,'passedGeometryAudit':geometry_pass,'metadataReviewRequired':bool(metadata_changes),'status':'GEOMETRY_PASS_NATIVE_ZINDEX_NORMALIZATION_REVIEW' if geometry_pass and metadata_changes else 'PASS' if not errors else 'FAIL','modifiedFillCount':13,'createdFillCount':1,'all14FullOuterPlusHolePathsExactlyMatchFrozenOperationsAtNative4DecimalMil':geometry_pass,'toleranceNotUsedForPathMatching':True,'nativeCallsPerformed':False,'fills':audit,'explicitMetadataChanges':metadata_changes,'errors':errors}
    target=HERE/'native-farvia-exact13fills1lobe-audit-20261018.json';target.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'passedGeometryAudit':geometry_pass,'metadataReviewRequired':bool(metadata_changes),'modified':13,'created':1,'errors':errors}))

if __name__=='__main__':main()
