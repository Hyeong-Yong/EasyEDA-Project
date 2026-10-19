"""Export numerical initial guesses with provenance; never changes vendor models."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
OUT = HERE.parent

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

phase3 = json.loads((HERE / "diagnostics-phase3-summary.json").read_text())
phase4 = json.loads((HERE / "diagnostics-phase4-summary.json").read_text())
phase1 = json.loads((HERE / "diagnostics-summary.json").read_text())
seed = phase3["results"][0]
values = seed["raw"]["point0"]
outputs = []
for filename, internal_only in [("warm-start-ideal-j2.inc",False),("warm-start-ideal-j2-internal.inc",True)]:
    guesses = {k:v for k,v in values.items() if k.startswith("v(xu" if internal_only else "v(")}
    target = OUT/filename
    text = "* ngspice numerical initial guesses only; not forced voltages or a DC solution.\n"
    text += "* Derived from original TI models by optran 0 0 0 100n 3m 0, Vin=0 V.\n"
    text += "* A separate fresh-process DC Newton solve must verify the final operating point.\n"
    text += "* See warm-start-manifest.json for provenance and validation.\n"
    text += "\n".join(f".nodeset {node}={value:.17g}" for node,value in guesses.items()) + "\n"
    target.write_text(text,encoding="ascii")
    outputs.append({"path":str(target),"sha256":digest(target),"voltage_guesses":len(guesses),"internal_only":internal_only})
    print(str(target),len(guesses))
manifest = {
    "purpose":"Numerical initial guesses for ngspice Newton iterations; not PSpice execution, not model modifications, and not authoritative final DC voltages.",
    "generator":str(Path(__file__).resolve()),
    "generator_sha256":digest(Path(__file__)),
    "original_hashes":phase1["original_hashes"],
    "originals_unchanged":phase3["originals_unchanged"] and phase4["originals_unchanged"],
    "seed_deck":seed["deck"],
    "seed_deck_sha256":digest(Path(seed["deck"])),
    "seed_raw":str(Path(seed["deck"]).with_suffix(".raw")),
    "seed_raw_sha256":digest(Path(seed["deck"]).with_suffix(".raw")),
    "seed_method":"Original ideal-bias J2 deck plus .save all; process-local ngbehavior=ps; optran 0 0 0 100n 3m 0. No rshunt or altered gmin.",
    "fresh_dc_validation":"Fresh process, default DC Newton iteration, compatibility init only, original TI model hashes preserved. No transient operating point fallback reported. Verified at Vin=0,+2,-2 V.",
    "dc_capacitor_validation":"Original physical C97/C122/C80/C156/C157 currents were all exactly 0 A in fresh DC solves with internal-only nodesets.",
    "outputs":outputs,
    "full_nodeset_validation":phase3["results"][1:4],
    "internal_nodeset_validation":phase4["results"],
    "recommended_reuse":"Use internal-only file when connecting a different shared bias/reference circuit. Preserve instance names or map each v(xu...) prefix to the corresponding generated instance. Nodesets are guesses; always require a successful finite final DC solve without convergence warnings."
}
(OUT/"warm-start-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
