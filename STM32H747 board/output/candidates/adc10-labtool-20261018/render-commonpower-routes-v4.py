"""Static routedV4 powerisland preview, notnativeGerber/DRC proof."""
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
HERE=Path(__file__).resolve().parent
src=(HERE/'render-commonpower-placement-v3.py').read_text(encoding='utf8')
src=src.replace('independent-pcb-placement-short-negative-commonpower-v3-proposal.json','independent-pcb-placement-short-negative-commonpower-v4-proposal.json')
# The reusedrenderer source itself is substituted by the smallwrapper.
src=src.replace("source=source.replace(\"independent-pcb-placement-rebased-eco-proposal.json\",\"independent-pcb-placement-short-negative-commonpower-v3-proposal.json\")","source=source.replace(\"independent-pcb-placement-rebased-eco-proposal.json\",\"independent-pcb-placement-short-negative-commonpower-v4-proposal.json\")")
src=src.replace('independent-commonpower-placement-v3-preview.png','independent-commonpower-routes-v4-preview.png')
exec(compile(src,str(HERE/'render-commonpower-placement-v3.py'),'exec'),globals())
p=HERE/'independent-commonpower-routes-v4-preview.png'
img=Image.open(p);d=ImageDraw.Draw(img)
routes=json.loads((HERE/'routing/commonpower-top-local-v4-final-review.json').read_text(encoding='utf8'))
def xy(q):return 45+(q[0]-25.5)*50,45+(36-q[1])*50
colors={'+5V':'#ba2b18','+5V_AFE':'#ef6b30','-3V_AFE':'#214bc0','AFE_PUMP_IN':'#bf9114','AFE_VNEG_RAW':'#13999a','AFE_FLY_N':'#9b36b5','AFE_FLY_P':'#536e17','AFE_NEG_FB':'#d73875'}
for q in routes['newLineCreates']:
    d.line([xy(q['startXYmm']),xy(q['endXYmm'])],fill=colors[q['net']],width=max(2,round(q['widthMm']*50)))
for name,net,pt in [('RAW5PUMP','+5V',(28.9,34.2)),('RAW5AFE','+5V',(28.3,22)),('PLUSOUT','+5V_AFE',(31,24.5)),('MINUSOUT','-3V_AFE',(40.3,31.7))]:
    a=xy(pt);r=.225*50;d.ellipse((a[0]-r,a[1]-r,a[0]+r,a[1]+r),outline=colors[net],width=3)
    d.text((a[0]+15,a[1]-8),name,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',11),fill=colors[net])
d.rectangle((0,0,img.width,38),fill='white');d.text((10,8),'V4 power island -35 TOP lines; ground/42via antipads/BOTTOM feeds pending',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16),fill='black')
d.rectangle((0,img.height-22,img.width,img.height),fill='white');d.text((10,img.height-17),'Static offline routing preview. No native copper applied by this audit. Original640VIA/799drills unchanged.',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',11),fill='black')
img.save(p);print(p)
