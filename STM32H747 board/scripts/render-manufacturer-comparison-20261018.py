"""Read-only official drawings; generated evidence images stay under output."""
from pathlib import Path
from pypdf import PdfReader
import subprocess
import sys
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1] / "output" / "3d-models-20261018" / "official-comparison"
for name in ["pj-051ah.pdf", "pj-051bh.pdf", "lpje101ahnl-drawing.pdf", "lpje101dnl-drawing.pdf"]:
    doc = PdfReader(ROOT / name)
    print(name)
    for i, page in enumerate(doc.pages):
        print(f"PAGE {i+1}: {page.extract_text()}")
        if (name.startswith("pj-") and i == 1) or name.startswith("lpje"):
            subprocess.run(["pdftoppm", "-f", str(i+1), "-l", str(i+1), "-singlefile", "-r", "130", "-png",
                            str(ROOT / name), str(ROOT / f"{name[:-4]}-page{i+1}")], check=True)
