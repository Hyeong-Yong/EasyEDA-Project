"""Use existing faithful source renderer with isolated inline output paths."""
import importlib.util
import argparse
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("adc_source_renderer", HERE.parent / "adc-dc-buffer/render-adc-native-source-qa.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.HERE = HERE
module.SOURCE = HERE / "06_ADC_TIMER_DAC_inline_candidate.epru"
module.CHECKPOINT = ROOT / "output/checkpoints/STM32H747_adc_dc_corners_j18_direction_v2_20261016.epro2"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--tag", default="adc-saved")
    args, _ = parser.parse_known_args()
    module.main()
    with Image.open(HERE / f"{args.tag}-source-visual-qa.png") as image:
        for i, offset in enumerate((0,335,665),1):
            bounds = (195+offset,95,550+offset,285)
            image.crop(tuple(int(2*x) for x in bounds)).save(HERE / f"{args.tag}-channel-{i}.png")
