"""Further isolated diagnostics, preserving the first run and all source models."""
import concurrent.futures
import json
from diagnose_convergence import HERE, SOURCE, MODELS, digest, run_case

base = SOURCE.read_text(encoding="utf-8-sig")
originals = {str(p): digest(p) for p in [SOURCE] + MODELS}
cases = []
for name, option in [
    ("rshunt10", ".options rshunt=1e10\n"),
    ("rshunt11", ".options rshunt=1e11\n"),
    ("nodeset", ".nodeset v(buf_j2)=0 v(drv_j2)=1.6473 v(adc_j2)=1.6473 v(xu20_j2.mid)=0.96325 v(xu10_j2.mid)=1.65\n"),
    ("pivtol18", ".options pivtol=1e-18\n"),
]:
    cases.append((name, base.replace(".temp 27", option + ".temp 27"), "ps"))
for name, optran in [("optran100us", "optran 0 0 0 1n 100u 0"), ("optran1ms", "optran 0 0 0 10n 1m 0")]:
    cases.append((name, base, "ps", optran))
single189 = f'''OPA189 isolated follower
.include "{MODELS[0].as_posix()}"
VP vp 0 5
VN vn 0 -3.01244
VI vi 0 0
X1 vi vo vp vn vo OPAx189
RL vo 0 1meg
.save v(vo) i(vp) i(vn)
.op
.end
'''
single320 = f'''OPA320-Q1 isolated follower
.include "{MODELS[1].as_posix()}"
VP vp 0 3.3
VI vi 0 1.65
X1 vi vo vp 0 vo OPAx320-Q1
RL vo 0 1meg
.save v(vo) i(vp)
.op
.end
'''
cases += [("single189", single189, "ps"), ("single320", single320, "ps")]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results = list(pool.map(run_case, cases))
unchanged = all(digest(p) == originals[str(p)] for p in [SOURCE] + MODELS)
(HERE / "diagnostics-phase2-summary.json").write_text(json.dumps({"originals_unchanged":unchanged,"results":results},indent=2),encoding="utf-8")
assert unchanged
