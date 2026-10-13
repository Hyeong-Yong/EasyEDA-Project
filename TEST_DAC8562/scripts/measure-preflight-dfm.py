"""Independent CAM geometry measurements against published 1oz/green rules."""
import importlib.util,json,sys,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
sys.path.insert(0,str(root/'.tools/pcb-python'))
s=importlib.util.spec_from_file_location('g',root/'scripts/audit-gerber.py');g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
from shapely.geometry import box,Point
from shapely.strtree import STRtree
archive=Path(sys.argv[1]) if len(sys.argv)>1 else root/'output/final-review/DAC8562_DAC_MCU_100x100_final_Gerber_DFM.zip'
with zipfile.ZipFile(archive) as z:
 _,_,mask=g.render(z.read('Gerber_TopSolderMaskLayer.GTS').decode(),vector=True)
 _,_,silk=g.render(z.read('Gerber_TopSilkscreenLayer.GTO').decode(),vector=True)
 _,_,cu=g.render(z.read(next(n for n in z.namelist() if n.endswith('.GTL'))).decode(),vector=True)
 polygons=list(mask.geoms) if hasattr(mask,'geoms') else [mask];tree=STRtree(polygons);near=[]
 for i,p in enumerate(polygons):
  for j in tree.query(p.buffer(.101)):
   j=int(j)
   if j<=i:continue
   distance=p.distance(polygons[j])
   if distance<.1-1e-5:near.append({'gapMm':distance,'opening1Bounds':list(p.bounds),'opening2Bounds':list(polygons[j].bounds)})
 result={'referenceGerber':str(archive),'boardProcessAssumption':'FR4, 2 layers, 1oz, green soldermask, 1.6mm nominal; not an order',
         'source':'https://jlcpcb.com/capabilities/pcb-','sourceCheckedDate':'2026-10-13',
         'minimumCopperToRoutedBoardEdgeMm':cu.distance(box(0,0,100,100).boundary),
         'silkscreenToTopMaskActualMm':silk.distance(mask),
         'soldermaskBridgesBelow01mm':sorted(near,key=lambda p:p['gapMm']),
         'soldermaskOpeningCountAfterUnion':len(polygons),'limitations':'Offline check only, not JLCDFM server/manufacturer approval. Mask-to-neighboring-track and paste/assembly checks require additional feature ownership review.'}
 print(z.read('Drill_PTH_Through.DRL').decode()[:600])
 destination=Path(sys.argv[2]) if len(sys.argv)>2 else out/'cam-dfm-measurements.json'
 destination.write_text(json.dumps(result,indent=2),encoding='utf8')
 print(json.dumps({k:v for k,v in result.items() if k!='soldermaskBridgesBelow01mm'},indent=2));print('Sub-0.1mm bridge count',len(near));print(near[:5])
