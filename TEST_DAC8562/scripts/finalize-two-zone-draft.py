"""Preserve the real EasyEDA PCB state without claiming that final DRC passed."""
import hashlib,importlib.util,json,sqlite3,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/pcb-two-zone'
target=out/'DAC8562 module_two_zone_PCB_DRC_pending.eprj2'
if target.exists():raise FileExistsError(target)
with sqlite3.connect((root/'DAC8562 module.eprj2').resolve().as_uri()+'?mode=ro',uri=True) as src:
    with sqlite3.connect(target) as dst:src.backup(dst)
with zipfile.ZipFile(out/'DAC8562 module_two_zone_PCB_DRC_pending.epro2') as z:
    for page in ['4e08f91f9a2c4fe4','e58bcc16379b10f4','e3a1c5f417017755']:
        f='IMAGE/'+page+'.webp'
        if f in z.namelist():(out/('draft-'+page+'.webp')).write_bytes(z.read(f))
v=json.loads((out/'native-final-validation.json').read_text(encoding='utf8'))
sch=json.loads((out.parent/'schematic-correction/erc-final-validation.json').read_text(encoding='utf8'))
route=json.loads((out/'routing-import-summary.json').read_text(encoding='utf8'))
comparison=json.loads((out/'protel-comparison.json').read_text(encoding='utf8'))
spec=importlib.util.spec_from_file_location('cio',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(spec);spec.loader.exec_module(io)
docs=io.read_export(out/'DAC8562 module_two_zone_PCB_DRC_pending.epro2')
before=io.read_export(root/'backups/DAC8562_live_before_schematic_correction_2026-10-12.epro2')
report={'status':'PCB DRC pending — do not fabricate or claim completion','nativeFile':str(root/'DAC8562 module.eprj2'),'draftCopy':str(target),'draftCopySha256':hashlib.sha256(target.read_bytes()).hexdigest(),
 'boardSizeMm':[100,100],'copperLayers':2,'zones':{'upper':'DAC8562: 106 parts','lower':'DAC_MCU: 48 parts'},'commonNets':['GND','VIN_RAW','VPOS12','VNEG12','MCU_3V3','DAC_HW_PGOOD'],
 'schematicErcPassed':all(p['passed'] and not p['details'] for p in sch['pages']),'pcbDrcPassed':v['passed'],'pcbDrcDetails':v['details'],'savedAndReopened':v['saved'] and v['closed'] and bool(v['reopened']),
 'electricalNetlistComparison':{'schematicComponents':154,'pcbComponents':154,'schematicNets':90,'pcbNets':90,'pinNetDifferences':comparison['netDifferences']},
 'placementAudit':json.loads((out/'placement-audit.json').read_text(encoding='utf8')),'routing':route,'panelUnchanged':io.data_hash(docs['458da9240aa63aad'])==io.data_hash(before['458da9240aa63aad']),
 'gitPushPerformed':False,'remaining':['Resolve EasyEDA Import Changes / Netlist Error without losing current routing or layout. Native comparison reports missing PCB linkage despite matching exported electrical pin assignments.','Inspect native Import Changes difference dialog; app screen access is not approved, and no blind Apply Changes should be performed.','Final PCB DRC and manufacturing-data verification remain incomplete.'],
 'limitations':['Ground copper is stored as six calculated SOLID regions because read-only POURED records are not imported through the v3.2 source API. Regenerate these regions after layout changes.','The original J1 generic 2x5 2.54mm female header is retained; verify its mating hardware at procurement.','High-input-impedance outputs only, not a 50-ohm load driver.','Prototype measurements must qualify rail startup, AVDD overshoot, relay release timing, output/cable stability and calibrated accuracy.','Older output/validated-revision files are superseded and are not fabrication references.']}
(out/'verification-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'draftCopy':str(target),'pcbDrcPassed':report['pcbDrcPassed'],'schematicErcPassed':report['schematicErcPassed'],'panelUnchanged':report['panelUnchanged'],'gitPushPerformed':False},ensure_ascii=False))
