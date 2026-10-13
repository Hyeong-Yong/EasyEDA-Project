Latest review: preflight-report.html / review-summary.json.
CAD original: ../../DAC8562 module.eprj2.
This folder contains review checkpoints, NOT a fabrication-approved release.

User-requested protected connection: R102.1 remains on singleton $2N434.
Its 10M bias path is not connected to MCU_RECEIVE_A. Do not silently repair it.
ERC global warning count is 1; activating either page returns the same count.
PCB netlist error is 1, physical pad map comparison identifies only R102.1.
Both layouts/pages/project identifiers are retained. PCB copper master was not edited.

BOM-confirmed.html/json: 154 physical parts, 158 symbol instances, 53 groups.
Exact MPN/package selection does not guarantee inventory or assembler acceptance.
Q2 2N7002P,215 is NRND, not confirmed discontinued; retained for this prototype.
J1 is selected as Samtec SSW-105-02-G-D after drawing/pad-hole comparison.

Native-final-schematic-proof.zip is the actual EasyEDA SVG export, not a thumbnail.
PNG render inspection is reproducible with scripts/render-preflight-svg.py.
The renderer omits an embedded logo image, not circuit parts or wiring.

DFM_REFERENCE_ONLY_NOT_FOR_FABRICATION.zip contains the runtime-mask reference
and clipped top silkscreen plus a prohibition note. Never order from it.
The individual pad API modifies runtime render properties, but the exported
footprint master remains at 2.008mil. The attempted default rule change also
did not change the exported project; the UI rule was restored to its old value.
No lasting CAD mask correction is claimed. The native file can regenerate the
8 close mask gaps. Fix/save the footprint's 10 top solder expansions to 1mil
(0.0254mm) and review newly regenerated CAM before manufacturing.
The runtime CAM has micron-level top copper aperture quantization differences.
See cam-geometry-comparison.json; do not claim byte-identical CAM copper.
The DFM copy differs from its runtime native export only in top silkscreen.
Combined PTH includes vias. Do not submit a redundant via drill as another pass.
Silk designator height 0.762mm is below the manufacturer recommendation of 1mm.
Factory DFM, stencil/assembly, full neighboring-track mask ownership, inventory
and mechanical enclosure/cable clearances remain unapproved.

Startup simulation is under ../../simulation/startup/:
24 startup-only screens pass; mixed 27-case run has 7 convergence failures.
TPS65131 supply ramps are prescribed, not a switching-circuit simulation.
All measured qualification was excluded at the user's request.

Original backups are in ../../backups/. Preflight-before live native and
consistent SQLite snapshots are retained; checkpoint-proof.json records hashes.
Older output folders and unrelated user files were not deleted or reset.
Only selected review deliverables should be committed; do not git add all.
