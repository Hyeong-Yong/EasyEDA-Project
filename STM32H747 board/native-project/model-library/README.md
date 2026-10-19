# STM32H747 private 3D model library

The user approved adding this private model-search directory on 2026-10-18. The settings UI required restarting the entire shared EasyEDA client, so registration was canceled to protect TEST_DAC8562. The original search path/defaults remain unchanged. Do not claim this directory is permanently registered yet.

STEP assets are uniquely prefixed `STM32H747_`. Model provenance, hashes, canonical frame, and native transform evidence are recorded under `output/3d-models-20261018`. These are visual assembly models, not manufacturing-clearance certification.

## Restart-free preview loader

The public extension library API can serve the five whitelisted STEP files in the current STM32 window without changing global search paths. Run from the repository root:

```powershell
node 'STM32H747 board/scripts/easyeda-safe-client.mjs' execute-file scripts/eda/load-stm32-public-3d-library-20261018.mjs
```

The guarded client targets only the recorded STM32 window and checks the exact project UUID. The loader checks the same project on every callback and verifies all file hashes. It neither opens nor edits TEST_DAC8562.

This is a session-dependent preview library. After restarting EasyEDA or reloading the bridge extension, load it again before opening 3D view. The observed current library ID is `extend_lib_STM32H747_3D_LOCAL5_20261018`; the API does not guarantee persistence across sessions. If the returned ID differs, stop and regenerate the five 3D references from the returned apply plan; do not replay historical apply batches blindly.

Permanent offline search-root registration remains a separate step for a time when restarting all EasyEDA windows is safe and expressly authorized.
