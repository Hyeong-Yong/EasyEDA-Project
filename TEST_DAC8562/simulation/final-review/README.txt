Current-design analog screening (2026-10-13)

These decks use the current 24.3k/100k DAC8562 and 14k/100k MCU
amplifier ratios, 100-ohm + 22pF dual feedback, fixed 100pF output,
and nominal energized relay contact resistance 0.1 ohm.
The STM32 receiver input model includes its 1k/10M bias loading and
OPA2277 unity buffer. The DAC and references and rails are ideal sources.
This is not a full component-level simulation of both schematic pages.

Install ngspice 47 with XSPICE from the official stable release:
https://ngspice.sourceforge.io/download.html
The default executable location is ignored .tools/ngspice47/Spice64/bin.
Alternatively set NGSPICE_BIN to ngspice_con.exe in an equivalent installation.
The runner generates a local .spiceinit when absent. Review an existing one:
PSPICE compatibility, the analog/spice2poly/table XSPICE libraries, and
documented optran 0 0 0 20n 100u 0 transient operating-point initialization.
Do not overwrite a different project's init configuration.

Run from TEST_DAC8562:
node simulation/final-review/run-final-review.mjs
python simulation/final-review/analyze-final-review.py

Python needs numpy and shapely; the existing project .tools/pcb-python
installation supplies these. Raw tables and logs are reproducible, local-only.
Commit decks, manifests and summary; they are sufficient to reproduce results.
The existing TI OPAx277 Final 1.4 model is unmodified (models/pspice).

54 AC/loop/25mV-step cases and 4 slow full-range plateau cases:
load 10k/100k/1M ohm, extra output cable 0/470/5000pF, ideal rails
+11.97231/-12.13V, 27C. Both channels share the verified same topology.
Initial direct OP/DC solves had numerical convergence failures. The
failed direct-DC manifest is retained; those sweeps are NOT called passes.
Range cases instead ramp from midscale and compare settled plateaus.
Reject solver failures, NaNs, wrong DC roots and nonphysical AC gains.

Separate arithmetic checks: 16 resistor-only 0.05% endpoint corners;
TPS3700 0.4V +/-1%, divider +/-0.1% threshold corners (excluding hysteresis);
PGOOD AND ENABLE truth table; Q3 gate rating and optocoupler current budget.
These are not transistor-level startup or safety simulations.

Not modeled/qualified: TPS65131 switching/startup/overshoot/ripple, LDO
startup/corner heat, real DAC INL/gain/reference drift, MCU cable drive,
relay coil flyback/release/bounce, real PCB parasitics and hot-plug faults.
Prototype measurements and fabrication/assembly DFM remain required.
