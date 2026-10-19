"""Static offline crop of separate twenty-cap placement variant, no native access."""
import json,math,runpy
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];MM=.0254
G=runpy.run_path(str(ROOT/'scripts/draft-adc10-bucket-placement-readonly-20261017.py'))
rows=G['PARSE'](ROOT/'output/validation/native-adc10-pcb-labtool_before-20261018.epru')
plan=json.loads((HERE/'independent-pcb-placement-short-negative-variant-v1.json').read_text(encoding='utf8'))
x0,y0,x1,y1,scale=5,131,25.5,143.5,55
margin=45
img=Image.new('RGB',(round((x1-x0)*scale)+2*margin,round((y1-y0)*scale)+2*margin),'white');d=ImageDraw.Draw(img)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',14);small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',11)
def xy(p):return margin+(p[0]-x0)*scale,margin+(y1-p[1])*scale
def bb(b):return (*xy((b[0],b[3])),*xy((b[2],b[1])))
for x in range(math.ceil(x0),math.floor(x1)+1):
    d.line([xy((x,y0)),xy((x,y1))],fill='#eeeeee');d.text((xy((x,y0))[0]-5,img.height-30),str(x),font=small,fill='#666666')
for y in range(math.ceil(y0),math.floor(y1)+1):
    d.line([xy((x0,y)),xy((x1,y))],fill='#eeeeee');d.text((5,xy((x0,y))[1]-5),str(y),font=small,fill='#666666')
for (k,r),b in rows.items():
    if k in ('LINE','ARC') and b['layerId']==1:
        a,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM)
        pts=G['arc'](a,z,b['angle']) if k=='ARC' else [a,z]
        if all(x<x0 or x>x1 or y<y0 or y>y1 for x,y in pts):continue
        n=b.get('netName','');c='#eab871' if ('PRE'in n or'DRV'in n or n=='ADC_BIAS_2V5') else '#aaaaaa'
        d.line([xy(p) for p in pts],fill=c,width=max(1,round(b['width']*MM*scale)))
    elif k=='VIA':
        x,y=b['centerX']*MM,b['centerY']*MM;r=b['viaDiameter']*MM/2
        if x0<=x<=x1 and y0<=y<=y1:d.ellipse(bb((x-r,y-r,x+r,y+r)),fill='#dddddd',outline='#333333')
for p in plan['edits']:
    if not x0<=p['xyMm'][0]<=x1 or not y0<=p['xyMm'][1]<=y1:continue
    changed=p['ref'] in plan['variantOnlyChangedRefs'];b=p['conservativeCourtBoundsMm']
    d.rectangle(bb(b),outline='#ff00aa' if changed else '#339ac5',width=2)
    for pad in p['pads']:
        c={'-3V_AFE':'#315bc4','+5V_AFE':'#bf3d27','GND':'#26712d','ADC_OFFSET_0V97':'#a03aaf'}.get(pad['net'],'#3d9b9a')
        d.rectangle(bb(pad['boundsMm']),fill=c,outline='#333333')
        a=xy(pad['centerMm']);d.text((a[0]-3,a[1]-5),pad['number'],font=small,fill='white')
    a=xy((p['xyMm'][0],b[3]));d.text((a[0]-14,a[1]-16),p['ref'],font=font,fill='black')
d.line([xy((9.9,136.5)),xy((8.18,134.8))],fill='#315bc4',width=2)
d.rectangle((0,0,img.width,37),fill='white');d.text((10,8),'J2 short-negative-cap variant: placement screen only; routing/ground pending',font=font,fill='black')
d.rectangle((0,img.height-22,img.width,img.height),fill='white');d.text((10,img.height-17),'Magenta: only changed C121/C97. Blue diagonal: 2.418 mm straight-line distance, NOT a proven route.',font=small,fill='black')
p=HERE/'independent-short-negative-placement-j2-variant-v1.png';img.save(p);print(p)
