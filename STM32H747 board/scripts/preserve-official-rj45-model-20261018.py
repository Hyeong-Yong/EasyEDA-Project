"""Download official linked CAD ZIP, validate archive paths, preserve original STEP.

No executable or model code is run. All bytes stay in the board-scoped output.
"""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import urllib.request
import zipfile
import sys
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "output" / "3d-models-20261018" / "source-models" / "manufacturer" / "LINK-PP-LPJE101-0AHNL"
URL = "https://www.l-p.com/upload/file/2023/03-15/020654246.zip"
PAGE = "https://www.l-p.com/products/457326.htm"
DEST.mkdir(parents=True, exist_ok=True)
request = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(request, timeout=40) as response:
    blob = response.read()
    final_url = response.url
    content_type = response.headers.get("Content-Type")
archive_path = DEST / "LPJE101-0AHNL-original.zip"
if archive_path.exists() and archive_path.read_bytes() != blob:
    raise RuntimeError("Existing original ZIP differs; refusing overwrite")
archive_path.write_bytes(blob)
manifest = dict(part="LPJE101-0AHNL", manufacturer="LINK-PP", source_product_page=PAGE,
                linked_download_label="3D Model: LPJE101-0AHNL.zip", source_url=URL,
                final_url=final_url, content_type=content_type, zip_bytes=len(blob),
                zip_sha256=hashlib.sha256(blob).hexdigest(), archive_entries=[],
                license="Manufacturer download; no open redistribution licence assumed.",
                status="Preserved only; no CAD/native import, geometry modification, or model execution.")
with zipfile.ZipFile(io.BytesIO(blob)) as archive:
    for item in archive.infolist():
        name = item.filename.replace("\\", "/")
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or ":" in name:
            raise RuntimeError(f"Unsafe archive path: {name}")
        entry = dict(name=name, bytes=item.file_size, compressed_bytes=item.compress_size)
        if not item.is_dir():
            data = archive.read(item)
            entry["sha256"] = hashlib.sha256(data).hexdigest()
            if pure.suffix.lower() in {".step", ".stp", ".pdf", ".txt"}:
                path = DEST / "extracted" / Path(*pure.parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.read_bytes() != data:
                    raise RuntimeError(f"Existing original archive member differs: {name}")
                path.write_bytes(data)
                entry["extracted_path"] = str(path.relative_to(ROOT))
                if pure.suffix.lower() in {".step", ".stp"}:
                    text = data.decode("utf-8", errors="replace")
                    entry["step_header"] = text[:text.index("DATA;")] if "DATA;" in text else text[:600]
        manifest["archive_entries"].append(entry)
(DEST / "source-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(manifest, indent=2, ensure_ascii=False))
