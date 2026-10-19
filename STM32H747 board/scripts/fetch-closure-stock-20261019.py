"""Fetch public LCSC Product facts; keep raw pages local, never reserve parts."""
from pathlib import Path
import concurrent.futures,datetime,hashlib,json,re,urllib.request,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/jlcpcb-closure-20261019'
data=json.loads((ROOT/'output/standard-values-20261019/review-data.json').read_text(encoding='utf8'))
tasks={x['LCSC Part #']:x['Proposed MPN'] for x in data['proposedParts']}
replacement='--replacement-x7r' in sys.argv
if replacement:tasks={'C59782':'CL10B105KO8NNNC','C3039701':'CL21B475KOFNFNE'}
def fetch(pair):
    code,expected=pair;url='https://www.lcsc.com/product-detail/'+code+'.html'
    try:
        raw=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25).read();text=raw.decode('utf8')
        p=next(json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>',text) if json.loads(x).get('@type')=='Product')
        (OUT/'stock'/(code+'-page.html')).write_bytes(raw)
        return {'code':code,'expectedMpn':expected,'mpn':p['mpn'],'manufacturer':p['brand']['name'],'stock':p['offers'].get('inventoryLevel'),'description':p.get('description'),'specifications':{x['name']:x['value'] for x in p.get('additionalProperty',[])},'datasheet':p.get('subjectOf',{}).get('url'),'url':url,'sourceSHA256':hashlib.sha256(raw).hexdigest(),'match':p['mpn'].casefold()==expected.casefold(),'reserved':False}
    except Exception as e:return {'code':code,'expectedMpn':expected,'error':str(e)}
rows=list(concurrent.futures.ThreadPoolExecutor(max_workers=5).map(fetch,tasks.items()))
(OUT/'stock'/('replacement-x7r-stock.json' if replacement else '107-parts-live-stock.json')).write_text(json.dumps({'checkedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'parts':rows},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps([{k:r.get(k) for k in ['code','mpn','stock','match','error']} for r in rows],ensure_ascii=False))
