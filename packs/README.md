# Domain packs

Each immediate subdirectory is one domain pack and contains a `pack.json` manifest.
The manifest declares the pack's identity metadata, license decision, source records,
and every knowledge file with its `sha256:<hex>` digest. The canonical JSON digest of
the complete manifest is the pack identity.

This directory contains data only. Loader code lives in `src/packs_loader/`.
