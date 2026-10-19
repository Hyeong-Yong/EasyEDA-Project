"""SecondsitesavoidpreservedPG12/13BottomandADC3_INP8innerfences."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
src=(HERE/'independent-pump-ground-via-review.py').read_text(encoding='utf8')
src=src.replace("('PUMP_CHIP_GND','U30','4',(32.4,29.5))","('PUMP_CHIP_GND','U30','4',(32.4,28.1))")
src=src.replace("('PUMP_INPUT_CAP_GND','C150','2',(27.7,28.0))","('PUMP_INPUT_CAP_GND','C150','2',(28.7,28.85))")
src=src.replace('independent-optional-pump-three-ground-vias-v1.json','independent-optional-pump-three-ground-vias-v2.json')
src=src.replace("'schema':'independent-optional-pump-three-local-ground-via-review'","'schema':'independent-optional-pump-three-local-ground-via-review-v2'")
exec(compile(src,str(HERE/'independent-pump-ground-via-review.py'),'exec'),globals())
