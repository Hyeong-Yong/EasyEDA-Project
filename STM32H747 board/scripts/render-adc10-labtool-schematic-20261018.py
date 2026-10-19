"""Render candidate or actual page using saved native symbols; no editor writes."""
import argparse
import importlib.util
import runpy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/candidates/adc10-labtool-20261018'


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--page',choices=['03','06'],required=True)
    p.add_argument('--source',type=Path)
    p.add_argument('--tag')
    a=p.parse_args()
    spec=importlib.util.spec_from_file_location('labtool_native_renderer',ROOT/'output/candidates/adc-dc-buffer/render-adc-native-source-qa.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.HERE=OUT
    m.SOURCE=a.source or OUT/('03_MCU_POWER_labtool_candidate.epru' if a.page=='03' else '06_ADC_TIMER_DAC_labtool_candidate.epru')
    m.CHECKPOINT=ROOT/'output/checkpoints/STM32H747_labtool_protection_libraries_20261018.epro2'
    m.GEN['read_checkpoint']=runpy.run_path(str(ROOT/'output/candidates/adc10-dc-buffer-20261017/build-adc10-dc-candidate.py'))['read_checkpoint']
    import sys
    sys.argv=[sys.argv[0],'--source',str(m.SOURCE),'--tag',a.tag or 'labtool-candidate-page'+a.page]
    m.main()


if __name__=='__main__':main()
