TPS7A4901 startup screening, 2026-10-13

Official TI unencrypted model: https://www.ti.com/lit/zip/sbvm528
Extract TPS7A4901_TRANS.LIB into ../../.tools/TPS7A49_unencrypted/.
Unmodified model SHA-256:
ec9d3d9086a45e3fe0753c74542d3b2aad2a0cf48926579f292f87348699007e
Model and third-party binaries are not redistributed in Git.

Requirements: ngspice 47 with XSPICE/spice2poly, Node.js, Python/numpy.
The runner uses ../../.tools/ngspice47/Spice64/bin/ngspice_con.exe.
Commands (from this directory):
  node run-startup.mjs
  python analyze-startup.py
  node run-startup.mjs --startup-only
  python analyze-startup.py --startup-only
Results/logs and .spiceinit are ignored; generated decks/manifests/summaries are tracked.

Results: startup-only 24/24 solver and range-screen passes.
Combined startup/shutdown/brownout 27 cases: 20 solver completions,
7 convergence failures at model UVLO/falling-rail discontinuity. Not 27 passes.
Peak simulated AVDD = 5.246308814858 V.
TI model VREF = 1.192 V, not datasheet typical 1.185 V; model was not tuned.
The initial few negative mV are behavioral-model artifacts, not an observed circuit event.

Limitations: VIN is a prescribed ideal 12V ramp. This is NOT a TPS65131
switching/startup simulation. No official TPS65131 switching model was found
in the manufacturer's listed simulation tools. No PWM/inductor saturation,
actual MLCC voltage/temperature bias, PCB parasitics, thermal model, cable
load, contact bounce or relay/opto propagation qualification is included.
Effective COUT sweep 0.5/1.0 is an assumed envelope, not a manufacturer guarantee.
Logic screening uses ideal rail windows plus assumed 2ms PG dwell and 5ms
initialization. It does not prove hardware guarantees or a universally sufficient
DAC initialization budget. Clear ENABLE GPIOs on PG fall and reinitialize after
every recovery. PGOOD cannot establish that the DAC received its configuration.
Flyback diode/relay release delays mean fast shutdown is not guaranteed glitch-free.
