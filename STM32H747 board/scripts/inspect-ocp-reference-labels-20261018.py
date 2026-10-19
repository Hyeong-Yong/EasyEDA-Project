"""Inspect imported XCAF labels without writing to source or invoking native UI."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "ocp-7.9.3.1.1"))
sys.stdout.reconfigure(encoding="utf-8")
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDF import TDF_LabelSequence
from OCP.TDataStd import TDataStd_Name
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.IFSelect import IFSelect_RetDone
doc = TDocStd_Document(TCollection_ExtendedString("Reference-audit"))
reader = STEPCAFControl_Reader()
reader.SetColorMode(True)
reader.SetNameMode(True)
status = reader.ReadFile(str(ROOT / "보드 자료" / "MCU_BOARD.step"))
assert status == IFSelect_RetDone
assert reader.Transfer(doc)
tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
labels = TDF_LabelSequence()
tool.GetShapes(labels)
for i in range(1, labels.Length()+1):
    label = labels.Value(i)
    attribute = TDataStd_Name()
    name = attribute.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attribute) else ""
    shape = tool.GetShape_s(label)
    print(i, name, "assembly", tool.IsAssembly_s(label), "reference", tool.IsReference_s(label), "null", shape.IsNull())
