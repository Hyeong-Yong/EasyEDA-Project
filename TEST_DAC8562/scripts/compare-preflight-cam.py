"""Compare actual geometry, not unstable/unused Gerber aperture numbers."""
import importlib.util,json,sys,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight';sys.path.insert(0,str(root/'.tools/pcb-python'))
s=importlib.util.spec_from_file_location('g',root/'scripts/audit-gerber.py');g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
rows=[]
with zipfile.ZipFile(root/'output/final-review/DAC8562_DAC_MCU_100x100_final_Gerber.zip') as old,zipfile.ZipFile(out/'DAC8562_RUNTIME_MASK_REFERENCE_ONLY_Gerber.zip') as new:
 for n in ('Gerber_TopLayer.GTL','Gerber_BottomLayer.GBL','Gerber_BoardOutlineLayer.GKO'):
  _,_,a=g.render(old.read(n).decode(),vector=True);_,_,b=g.render(new.read(n).decode(),vector=True)
  rows.append({'layer':n,'symmetricDifferenceAreaMm2':a.symmetric_difference(b).area,'hausdorffDistanceMm':a.hausdorff_distance(b),'oldBounds':list(a.bounds),'newBounds':list(b.bounds)})
result={'layers':rows,'explanation':'Native master component/pad/trace/via/fill and pad-net records are unchanged. Gerber uses unstable unused aperture definitions and quantized generated pad dimensions. Actual layer geometry is compared separately. Not a byte-identical CAM claim.','fabricationReleased':False}
result['maximumBoundaryDeviationMm']=max(r['hausdorffDistanceMm'] for r in rows)
result['exactGeometryEquality']=all(r['symmetricDifferenceAreaMm2']==0 for r in rows)
(out/'cam-geometry-comparison.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result,indent=2))
