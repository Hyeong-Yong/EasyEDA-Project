"""Read native project exports without changing project/PCB data."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def documents(source):
    result, doc, client = {}, None, ""
    for line in source.splitlines():
        if "||" not in line:
            continue
        left, right = line.split("||", 1)
        header = json.loads(left)
        data = right.removesuffix("|")
        payload = json.loads(data) if data else ""
        if header["type"] == "DOCHEAD":
            doc = result.setdefault(payload["uuid"], {"head": payload, "records": {}})
            client = payload.get("client", "")
            doc["head"] = payload
            continue
        key = (header["type"], header.get("id", ""))
        prior = doc["records"].get(key)
        rank = (header.get("ticket", 0), client)
        if prior is None or rank[0] > prior[0].get("ticket", 0) or (rank[0] == prior[0].get("ticket", 0) and client <= prior[2]):
            doc["records"][key] = (header, payload, client)
    for doc in result.values():
        doc["records"] = {k: (h, p) for k, (h, p, _) in doc["records"].items() if isinstance(p, dict)}
    return result


def read_export(path):
    with zipfile.ZipFile(path) as archive:
        source = archive.read(next(n for n in archive.namelist() if n.endswith(".epru"))).decode()
    return documents(source)


def attrs(doc):
    result = {}
    for (kind, ident), (header, payload) in doc["records"].items():
        if kind == "ATTR":
            result.setdefault(payload["parentId"], {})[payload["key"]] = payload.get("value")
    return result


def source_of(doc):
    lines = [json.dumps({"type": "DOCHEAD"}, separators=(",", ":")) + "||" + json.dumps(doc["head"], separators=(",", ":")) + "|"]
    for header, payload in doc["records"].values():
        lines.append(json.dumps(header, separators=(",", ":")) + "||" + json.dumps(payload, separators=(",", ":")) + "|")
    return "\n".join(lines) + "\n"


def data_hash(doc):
    data = [(kind, ident, p) for (kind, ident), (_, p) in sorted(doc["records"].items())]
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


if __name__ == "__main__":
    export = Path(sys.argv[1])
    docs = read_export(export)
    for ident, doc in docs.items():
        kind = doc["head"]["docType"]
        if kind in ("PCB", "PANEL"):
            print(kind, ident, len(doc["records"]), data_hash(doc))
        if kind != "SCH_PAGE":
            continue
        a = attrs(doc)
        print("PAGE", ident, "records", len(doc["records"]))
        for (kind, pid), (_, p) in doc["records"].items():
            if kind == "COMPONENT":
                props = a.get(pid, {})
                if props.get("Designator"):
                    print(pid, p, json.dumps(props, ensure_ascii=False))
            if kind == "TEXT":
                print("TEXT", pid, p)
    with zipfile.ZipFile(export) as archive:
        if "IMAGE/e58bcc16379b10f4.webp" in archive.namelist():
            preview = ROOT / "output/schematic-correction"
            preview.mkdir(parents=True, exist_ok=True)
            (preview / "original-page1.webp").write_bytes(archive.read("IMAGE/e58bcc16379b10f4.webp"))
