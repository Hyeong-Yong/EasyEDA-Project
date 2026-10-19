"""Offline exact-source renderer wrapper; no EasyEDA/API/UI access."""
import argparse
import importlib.util
import runpy
from pathlib import Path
from PIL import Image

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
spec=importlib.util.spec_from_file_location("adc10_source_renderer",HERE.parent/"adc-dc-buffer/render-adc-native-source-qa.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.HERE=HERE
module.SOURCE=HERE/"06_ADC_TIMER_DAC_adc10_candidate.epru"
module.CHECKPOINT=ROOT/"output/checkpoints/STM32H747_before_adc10_20261017.epro2"
module.GEN["read_checkpoint"]=runpy.run_path(str(HERE/"build-adc10-dc-candidate.py"))["read_checkpoint"]

if __name__=="__main__":
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument("--tag",default="adc10-proposed")
    args,_=parser.parse_known_args()
    module.main()
    crops={"adc1-bank":(190,90,1220,285),"adc2-bank":(190,260,1220,455),"adc3-bank":(190,430,1575,625),
           "timer-dac-context":(185,610,1450,840),"notes-j18-context":(100,780,1420,1090)}
    with Image.open(HERE/f"{args.tag}-source-visual-qa.png") as image:
        for label,box in crops.items():
            image.crop(tuple(round(v*2) for v in box)).save(HERE/f"{args.tag}-{label}.png")
