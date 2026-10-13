"""Parse fresh native fabrication output and render the actual exported layers."""
import importlib.util
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('gerber',root/'scripts/audit-gerber.py')
g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
g.out=root/'output/final-review'
g.audit(g.out/'DAC8562_DAC_MCU_100x100_final_Gerber.zip',expected_vias=134)
