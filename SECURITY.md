# Security and scope

Keep source media, engine manifests, model caches, logs, tokens and keys out of Git. Generated local settings are ignored. Conversion does not require a cloud account.

Only the CPU helper requests elevation. The converter and app stay unelevated. Review the sensor driver's signature and upstream source before installing it. Do not disable Windows security or signing policy to obtain readings.

Setup verifies pinned archive hashes and rejects paths outside its extraction directory. Hashes do not replace trust in publishers. Model ZIPs include executable inference code: use recorded official files.

Thermal supervision has polling delay and cannot cover OS hangs, power faults, GPU VRAM/hotspot temperatures or every cooling failure. Required readings must exist before work starts. GPU-only mode explicitly leaves the CPU unmonitored.

Report reproducible problems without uploading movies, private logs or secrets. For a sensitive issue, use the contact method on the owner's GitHub profile instead of posting credentials or private details publicly.
