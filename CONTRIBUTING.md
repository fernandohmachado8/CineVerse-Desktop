# Contributing

Use a small branch, describe the user-visible behavior and include relevant validation. Keep interface state, native IPC and conversion stages separate. Preserve source timing and provenance; never label synthesized pixels as recovered footage.

Run `npm ci`, `npm test`, `npm run build`, `npm run format:check` and `python -m unittest discover -s tests -v`. On Windows also run `python -m unittest discover -s thermal -v`. Tests use generated fixtures or disposable processes, never copyrighted clips or deliberately overheated hardware.

GPU checks use short, explicit previews. Never start a full film as a side effect of setup, launch, recovery, CI or a test. Separate hardware evidence from CPU-only checks. Do not commit settings, dependency binaries, weights, input media or private logs.

Update source pins, hashes, notices and relevant tests together when changing dependencies. Do not silently substitute a model or filling method when a download fails.
