"""Non-overwriting validated native copy; assert CAD, export and Gerber evidence."""
import hashlib,importlib.util,json,math,sqlite3,sys,zipfile
from collections import Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/final-review';proof=root/'output/readability'
read=lambda p:json.loads(p.read_text(encoding='utf8'))
pcb=read(proof/'pcb-reopened.json');sch=read(proof/'native-validation.json')
assert pcb['saved'] and pcb['closed'] and pcb['reopened'] and pcb['passed'] and not pcb['details']
assert all(p['saved'] and p['reopened'] and p['passed'] and not p['details'] for p in sch['pages'])
assert read(proof/'physical-pcb-audit.json')['passed']
assert read(out/'q3-name-change-audit.json')['layoutRoutingCopperPadNetsUnchanged']
assert read(out/'schematic-export-audit.json')['passed']
scope=read(out/'pcb-edit-scope-audit.json');assert scope['passed']
assert read(root/'simulation/final-review/summary.json')['passed']
dfm=read(out/'gerber-dfm-processing.json');gerber=read(out/'gerber-dfm-audit.json')
assert dfm['copperMasksOutlineDrillsByteIdentical'] and dfm['clearanceToMaskActuallyMeasuredMm']>=.149
assert gerber['unsupportedRecords']==0 and gerber['viaDrillCount']==134
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py')
io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
export=out/'DAC8562 module_final_review_ERC_DRC_clean.epro2'
docs=io.read_export(export);before=io.read_export(root/'backups/DAC8562_live_before_readability_2026-10-12.epro2')
assert io.data_hash(docs['458da9240aa63aad'])==io.data_hash(before['458da9240aa63aad'])
live=io.documents(pcb['source'])['4e08f91f9a2c4fe4'];portable=docs['4e08f91f9a2c4fe4'];normalization=Counter()
for key in set(live['records'])|set(portable['records']):
    a=live['records'].get(key,(None,None))[1];b=portable['records'].get(key,(None,None))[1]
    if a==b:continue
    kind=key[0]
    if kind=='LINE':
        assert a is None and b is not None and math.hypot(b['startX']-b['endX'],b['startY']-b['endY'])<=.101
    elif kind=='POURED':assert a is None and ('POUR',json.loads(key[1])[1]) not in live['records']
    elif kind=='RULE_SELECTOR':
        assert b is None and a['copperValue']==a['innerPlaneValue']=={}
        assert a['ruleKeyValue'] in ({},{'NET_LENGTH_TOLERANCE':['default',None]})
    elif kind=='LAYER':assert {k:v for k,v in a.items() if k!='inactiveColor'}=={k:v for k,v in b.items() if k!='inactiveColor'}
    elif kind in ('META','ELE_PLACEHOLDER'):assert a is None
    else:raise AssertionError(('Unexpected exported PCB difference',key))
    normalization[kind]+=1
counts=Counter(k[0] for k in live['records']);assert counts['COMPONENT']==154 and counts['PAD_NET']==489
target=out/'DAC8562 module_final_review_ERC_DRC_clean.eprj2'
if target.exists() and '--verify-existing' not in sys.argv:raise FileExistsError(target)
if not target.exists():
    with sqlite3.connect((root/'DAC8562 module.eprj2').resolve().as_uri()+'?mode=ro',uri=True) as src:
        with sqlite3.connect(target) as dst:src.backup(dst)
with sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True) as dst:
    assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
result={'status':'CAD checks complete; conditional prototype release, fabrication DFM and hardware qualification pending',
        'date':'2026-10-13','schematicErcPassed':True,'pcbDrcPassed':True,'savedAndReopened':True,
        'nativeFile':str(target),'nativeFileSha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'portableProjectExport':export.name,'portableExportSha256':hashlib.sha256(export.read_bytes()).hexdigest(),
        'nativePrimitiveCounts':dict(counts),'pcbExportNormalizationDifferences':dict(normalization),
        'exportNormalizationExplanation':'Only placeholders, empty default selectors, inactive colors, sub-0.101mil degenerate tracks and orphan historical POURED caches differ. All meaningful PCB components, pad nets and geometry match the saved/reopened native source.',
        'schematicExportAudit':'schematic-export-audit.json','q3DisplayNameOnlyAudit':'q3-name-change-audit.json',
        'physicalEditScopeAudit':scope,
        'panelDecision':'Single 100x100mm, Panel1 unchanged','panelUnchanged':True,'copperLayers':2,
        'nativeGerber':dfm['input'],'dfmGerber':dfm['output'],'dfmOnlySilkscreenChanged':True,
        'gerberPreview':'gerber-dfm-top-preview.png','gerberVisualInspection':'Top preview visually inspected; upper/lower zones, four holes and edge SMA positions preserved.',
        'drillNote':'Combined PTH contains vias. Via-only DRL is redundant reference, not a second drilling pass.',
        'schematicImageExportLimitation':'Native PNG/SVG export times out in connected EasyEDA 3.2.149. Cached project thumbnails are not asserted as current final schematic visual proof. Current source geometry, saved/reopened ERC and portable export topology were independently verified.',
        'noOrderPlaced':True,'gitDeliveryEvidence':'Verify actual repository commit and remote HEAD; CAD proof does not predict future push.'}
(out/'release-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k not in ('nativePrimitiveCounts','pcbExportNormalizationDifferences')},ensure_ascii=False,indent=2))
