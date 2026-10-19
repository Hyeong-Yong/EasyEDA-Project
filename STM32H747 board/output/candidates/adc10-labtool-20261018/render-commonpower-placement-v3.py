"""Reuse static renderer without running its legacy output actions."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
source=(HERE/'render-independent-placement-preview.py').read_text(encoding='utf8')
source=source.split('print(json.dumps(')[0]
source=source.replace("independent-pcb-placement-rebased-eco-proposal.json","independent-pcb-placement-short-negative-commonpower-v3-proposal.json")
source=source.replace("independent-placement-power-preview.png","independent-commonpower-placement-v3-preview.png")
exec(compile(source,str(HERE/'render-independent-placement-preview.py'),'exec'),globals())
print(draw_region('independent-commonpower-placement-v3-preview.png',(25.5,20,44,36),50))
