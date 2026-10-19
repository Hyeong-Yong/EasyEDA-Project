"""Save a consistent native-file copy and an explicitly incomplete ERC report."""
import hashlib
import importlib.util
import json
import sqlite3
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/schematic-correction'
original=ROOT/'DAC8562 module.eprj2'
corrected=OUT/'DAC8562 module_schematic_corrected.eprj2'
if corrected.exists():
    raise FileExistsError('Do not overwrite a delivered revision copy')
with sqlite3.connect(original.resolve().as_uri()+'?mode=ro',uri=True) as src:
    with sqlite3.connect(corrected) as dst:
        src.backup(dst)
s=importlib.util.spec_from_file_location('io_c',ROOT/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
with zipfile.ZipFile(OUT/'DAC8562 module_schematic_corrected.epro2') as z:
    for name in z.namelist():
        if name.startswith('IMAGE/') and name.endswith('.webp'):
            (OUT/('final-'+Path(name).name)).write_bytes(z.read(name))
v=json.loads((OUT/'live-validation.json').read_text(encoding='utf8'))
bom=[]
for page in v['pages']:
    doc=next(iter(io.documents(page['source']).values()))
    attrs=io.attrs(doc);seen=set()
    for (kind,pid),(_,p) in doc['records'].items():
        a=attrs.get(pid,{})
        if kind!='COMPONENT' or not a.get('Designator') or a['Designator'] in seen:continue
        seen.add(a['Designator'])
        bom.append({'page':page['page'],'designator':a['Designator'],**{k:a.get(k) for k in ['Name','Value','Manufacturer','Manufacturer Part','Supplier','Supplier Part','Device','Symbol','Footprint','Tolerance','Temperature Coefficient']}})
    (OUT/('DAC8562.final-source.txt' if page['page']=='e58bcc16379b10f4' else 'DAC_MCU.final-source.txt')).write_text(page['source'],encoding='utf8',newline='\n')
(OUT/'BOM.json').write_text(json.dumps(bom,ensure_ascii=False,indent=2),encoding='utf8')
connectivity=json.loads((OUT/'live-connectivity-audit.json').read_text(encoding='utf8'))
summary={'project':'DAC8562 module','scope':'Only the two existing schematic pages; no PCB/panel work.',
 'savedFile':str(original),'revisionCopy':str(corrected),'revisionCopySha256':hashlib.sha256(corrected.read_bytes()).hexdigest(),
 'backupFile':str(ROOT/'backups/DAC8562 module_before_schematic_correction_2026-10-12_17-37-46.eprj2'),
 'liveBackup':str(ROOT/'backups/DAC8562_live_before_schematic_correction_2026-10-12.epro2'),
 'nativeSaved':all(p['saved'] for p in v['pages']),'saveReopenVerified':json.loads((OUT/'save-reopen-check.json').read_text(encoding='utf8')),
 'ercPassed':False,'ercStatus':'One warning remains in the full schematic. Detail unavailable through v3.2 API; native UI access was not approved. Do not classify this revision as manufacturing-ready.',
 'connectivity':connectivity,'physicalParts':len(bom),'missingManufacturerPart':[x['designator'] for x in bom if not x['Manufacturer Part']],
 'changes':['Q1 Si2323DS-T1-E3 -> Si2323DDS-T1-GE3, pin map preserved.','C4 CN=4.7nF, C5 CP=10nF.','U2 TPS7A4901DGNR; OUT1 FB2 NC3 GND4 EN5 NR/SS6 DNC7 IN8 EP9. Nominal 1.185*(1+34k/10k)=5.214V.','DAC gain resistors: 100k/24.3k, Susumu RG1608N 0.05%, 10ppm/C, manual procurement.','DAC-control pull-ups now use DAC AVDD; TTL/Ioff buffers and default-muted output relay added.','+12V/AVDD/-12V power-good supervision added; negative domain uses optocoupler.','Page 2 DAC_MCU has two SMA receiver/buffer/difference-amplifier channels, tracking external MCU VREF+. Separate input/output relay enables.'],
 'limitations':['Prior output/validated-revision projects are superseded and must not be used for fabrication. Their TPS7A49 mapping was incorrect.','The MCU receiver assumes external VDDA/VREF+=3.3V, high-Z output loading, common ground. No 50-ohm termination.','Source-side cable driver may be needed to meet the MCU DAC CL<=50pF condition.','Relay release is not an instantaneous clamp on unexpected power loss.','AVDD overshoot, power-rail/output transients, effective capacitor values, thermal performance, cable stability, load capability and calibrated accuracy need physical qualification.','PCB is intentionally unchanged and does not implement the revised schematic.','R5/inductor/compensation conditional qualifications still require input-slew and load measurements.']}
(OUT/'verification-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:summary[k] for k in ['revisionCopy','nativeSaved','ercPassed','physicalParts','missingManufacturerPart']},ensure_ascii=False))
