"""Render actual native SVG export for final schematic visual inspection."""
import json,sys,xml.etree.ElementTree as ET
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=Path(sys.argv[2]) if len(sys.argv)>2 else root/'output/manufacturing-preflight'
out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(root/'.tools/pcb-python'))
import pymupdf
results=[]
svg_dir=Path(sys.argv[1]) if len(sys.argv)>1 else out/'native-svg'
for path in svg_dir.glob('*.svg'):
 node=ET.parse(path).getroot();print(path.name,{k:v for k,v in node.attrib.items() if k in ('width','height','viewBox')})
 svg=pymupdf.open(path);doc=pymupdf.open(stream=svg.convert_to_pdf(),filetype='pdf');pg=doc[0]
 scale=2400/pg.rect.width
 target=out/('DAC8562-native.png' if '1-DAC8562' in path.name else 'DAC_MCU-native.png')
 pg.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).save(target)
 results.append({'source':path.name,'render':target.name,'pageBounds':list(pg.rect),'pixelScale':scale})
 # Native text bounds provide exact crop coordinates without an assumed
 # relationship between API schematic units and export SVG viewBox.
 vx,vy,vw,vh=map(float,node.attrib['viewBox'].split())
 regions=[('regulator',(880,-2765,1535,-2460)),('control-06',(0,-1550,1620,-80))] if '1-DAC8562' in path.name else [('channel-A',(60,-2110,1620,-1660)),('channel-B',(60,-1660,1620,-1210)),('mcu-relays',(10,-790,1640,-235))]
 for name,(left,top,right,bottom) in regions:
  clip=pymupdf.Rect((left-vx)*pg.rect.width/vw,(top-vy)*pg.rect.height/vh,(right-vx)*pg.rect.width/vw,(bottom-vy)*pg.rect.height/vh)
  pg.get_pixmap(matrix=pymupdf.Matrix(2,2),clip=clip,alpha=False).save(out/(name+'-native-crop.png'))
(out/'schematic-render-proof.json').write_text(json.dumps(results,indent=2),encoding='utf8')
