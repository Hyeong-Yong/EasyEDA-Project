import json
from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'output/validated-revision/library'
search = json.loads((root/'search-results.json').read_text())
choices = {'QPM':'Si2323DDS-T1-GE3','LDO':'TPS7A4901DGNR','RELAY':'G6K-2F-Y DC5',
           'MON':'TPS3700DDCR','BUF':'SN74LV125ATPWR','OPTO':'LTV-817S-TA1',
           'NFET':'2N7002P,215','DIO':'1N4148W-G3-18','AND':'SN74LVC1G08DBVR',
           'HEADER':'TSW-105-07-G-D','CO10':'CL21A106KAYNNNE','R10M':'RC0603FR-0710ML',
           'R34K':'RT0603BRD0734KL','R312K':'RT0603BRD07312KL','R320K':'RT0603BRD07320KL',
           'R200K':'RT0603BRD07200KL', 'DRIVER':'AO3400A','INV':'SN74LVC1G04DBVR',
           'R10K':'RT0603BRD0710KL','R100K':'RT0603BRD07100KL',
           'R24K3':'RT0603BRD0724K3L','R14K':'RT0603BRD0714KL'}
selected = {}
for key, mpn in choices.items():
    matches = [p for p in search[mpn] if p.get('manufacturerId') == mpn]
    if not matches: raise ValueError('No exact manufacturer part: '+mpn)
    selected[key] = matches[0]
(root/'selected.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2),encoding='utf8')
print('Selected',len(selected),'exact manufacturer part numbers')
