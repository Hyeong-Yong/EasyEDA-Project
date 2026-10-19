"""Static, explicitly non-manufacturing view of the placement proposal."""
import json
import math
import runpy
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
G = runpy.run_path(str(ROOT / 'scripts/draft-adc10-bucket-placement-readonly-20261017.py'))
MM = .0254
rows = G['PARSE'](ROOT / 'output/validation/native-adc10-pcb-labtool_before-20261018.epru')
plan = json.loads((HERE / 'independent-pcb-placement-rebased-eco-proposal.json').read_text(encoding='utf8'))
font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 13)
small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 11)
title = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 18)
colors = {'+5V_AFE':'#bf3d27','-3V_AFE':'#315bc4','GND':'#26712d','ADC_OFFSET_0V97':'#a03aaf'}


def draw_region(name, bounds, scale):
    x0,y0,x1,y1 = bounds
    margin = 45
    img = Image.new('RGB',(round((x1-x0)*scale)+2*margin,round((y1-y0)*scale)+2*margin),(255,255,255))
    d = ImageDraw.Draw(img)
    def xy(p):return (margin+(p[0]-x0)*scale, margin+(y1-p[1])*scale)
    def bb(b):
        a,z=xy((b[0],b[3])),xy((b[2],b[1]));return (*a,*z)
    for x in range(math.ceil(x0),math.floor(x1)+1):
        d.line([xy((x,y0)),xy((x,y1))],fill='#eeeeee',width=1)
        if x%2==0:d.text((xy((x,y0))[0]-7,img.height-30),str(x),font=small,fill='#555555')
    for y in range(math.ceil(y0),math.floor(y1)+1):
        d.line([xy((x0,y)),xy((x1,y))],fill='#eeeeee',width=1)
        if y%2==0:d.text((3,xy((x0,y))[1]-5),str(y),font=small,fill='#555555')
    for (kind,rid),b in rows.items():
        if kind in ('LINE','ARC') and b['layerId']==1:
            a,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM)
            pts=G['arc'](a,z,b['angle']) if kind=='ARC' else [a,z]
            net=b.get('netName','')
            color='#eab871' if ('PRE' in net or 'DRV' in net or net=='ADC_BIAS_2V5') else '#9c9c9c'
            if all(x<x0 or x>x1 or y<y0 or y>y1 for x,y in pts):continue
            d.line([xy(p) for p in pts],fill=color,width=max(1,round(b['width']*MM*scale)))
        elif kind=='VIA':
            x,y=b['centerX']*MM,b['centerY']*MM
            if x0<=x<=x1 and y0<=y<=y1:
                r=b['viaDiameter']*MM/2
                d.ellipse(bb((x-r,y-r,x+r,y+r)),fill='#dddddd',outline='#444444',width=1)
    for p in plan['edits']:
        x,y=p['xyMm']
        if not (x0<=x<=x1 and y0<=y<=y1):continue
        rect=p['conservativeCourtBoundsMm']
        d.rectangle(bb(rect),outline='#339ac5',width=2)
        for pad in p['pads']:
            d.rectangle(bb(pad['boundsMm']),fill=colors.get(pad['net'],'#3d9b9a'),outline='#333333',width=1)
            px,py=xy(pad['centerMm']);d.text((px-3,py-5),pad['number'],font=small,fill='white')
        px,py=xy((x,rect[3]));d.text((px-14,py-15),p['ref'],font=font,fill='black')
    d.rectangle((0,0,img.width,38),fill='white')
    short={'independent-placement-j2-preview.png':'J2 channel','independent-placement-ref-preview.png':'Reference island','independent-placement-power-preview.png':'Power island'}[name]
    d.text((10,7),short+' - prospective placement; NOT routed/DRC-approved',font=title,fill='black')
    d.rectangle((0,img.height-22,img.width,img.height),fill='white')
    d.text((10,img.height-16),'Grey: source copper/vias. Orange: old AFE rework. Blue: conservative package envelopes.',font=small,fill='#333333')
    path=HERE/name
    img.save(path)
    return str(path)


print(json.dumps({'previews':[draw_region('independent-placement-j2-preview.png',(5,131.5,25.5,144),44),draw_region('independent-placement-ref-preview.png',(18.5,65,33.5,87),44),draw_region('independent-placement-power-preview.png',(26,19,42.5,36),44)],'notLivePcbRender':True}))
