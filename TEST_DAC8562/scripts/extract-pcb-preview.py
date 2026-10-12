import zipfile,sys
from pathlib import Path
out=Path(__file__).resolve().parents[1]/'output/pcb-two-zone'
archive=Path(sys.argv[1]) if len(sys.argv)>1 else out/'placement-checkpoint.epro2'
prefix=sys.argv[2] if len(sys.argv)>2 else 'placement'
with zipfile.ZipFile(archive) as z:
    for page in ['4e08f91f9a2c4fe4','e58bcc16379b10f4','e3a1c5f417017755']:
        name='IMAGE/'+page+'.webp'
        if name in z.namelist():
            target=out/(prefix+'-'+page+'.webp');target.write_bytes(z.read(name));print(target)
