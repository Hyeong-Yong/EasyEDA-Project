"""Produce a reusable U32 (OPA189) 5 V follower internal-node seed."""
import json
from pathlib import Path
from diagnose_convergence import HERE, MODELS, digest, run_case

model_hash = digest(MODELS[0])
base = f'''Original TI OPA189 standalone U32, single 5 V rail, 0.969 V follower
.include "{MODELS[0].as_posix()}"
.options reltol=1e-5 abstol=1e-12 vntol=1e-7 itl1=500 itl4=1000
.temp 27
VP vp 0 5
VI vi 0 0.969
XU32 vi off vp 0 off OPAx189
RL off 0 1meg
.save all
.op
.end
'''
seed = run_case(("u32_seed_optran",base,"ps","optran 0 0 0 1u 3m 0"))
assert seed["raw"]["all_finite"]
seed_nodes = {k:v for k,v in seed["raw"]["point0"].items() if k.startswith("v(xu32.")}
nodesets = "\n".join(f".nodeset {k}={v:.17g}" for k,v in seed_nodes.items())
warm = base.replace(".temp 27",nodesets + "\n.temp 27")
dc = run_case(("u32_fresh_dc",warm,"ps"))
dc_log = Path(dc["deck"]).with_suffix(".log").read_text(errors="replace")
dc["transient_op_used"] = "Transient op started" in dc_log
assert dc["returncode"] == 0 and dc["raw"]["all_finite"] and not dc["transient_op_used"]
final_nodes = {k:v for k,v in dc["raw"]["point0"].items() if k.startswith("v(xu32.")}
output = HERE.parent / "warm-start-u32-5v.inc"
header = "* ngspice U32 internal-node guesses only, original TI OPA189 on single 5 V rail.\n"
header += "* Standalone follower Vin=0.969 V; optran seed then successful fresh DC Newton.\n"
header += "* No rshunt/gmin changes, forced voltages, or edits to manufacturer model.\n"
output.write_text(header + "\n".join(f".nodeset {k}={v:.17g}" for k,v in final_nodes.items()) + "\n",encoding="ascii")
unchanged = digest(MODELS[0]) == model_hash
manifest = {
    "output":str(output),"output_sha256":digest(output),"internal_voltage_guesses":len(final_nodes),
    "model":str(MODELS[0]),"model_sha256":model_hash,"original_model_unchanged":unchanged,
    "seed":seed,"fresh_dc":dc,"generator":str(Path(__file__).resolve()),"generator_sha256":digest(Path(__file__)),
    "seed_method":"optran 0 0 0 1u 3m 0; original model; ngbehavior=ps; no rshunt/gmin edits",
    "final_method":"Fresh process with internal-only seed nodesets and default DC Newton iterations; no transient operating point fallback; saved all voltages.",
    "reuse":"Instance must be XU32 or map xu32 prefix to the intended instance. Guesses only; final shared circuit still needs a successful finite Newton solve."
}
(HERE.parent/"warm-start-u32-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
print(json.dumps({"output":str(output),"nodes":len(final_nodes),"dc_out":dc["raw"]["point0"]["v(off)"],"true_dc":not dc["transient_op_used"]}))
assert unchanged
