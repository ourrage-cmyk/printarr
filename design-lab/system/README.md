# Design system assets

- `assets/ornaments/`: 26 pieces on the 3-dot pitch, 1-bit PNG, black ink on white. One file per piece. Listed in `assets/manifest.json`.
- `assets/round/sys-*.png`: the system ticket with one piece applied (confirmation round, arena System tab).
- `assets/round/old-*.png`: the old ornament ticket for the same concept (pass 1, Inter body). Used as the comparison side.
- `assets/contact-sheet.png`: every standalone piece on one sheet.
- `scripts/build_system.py`: rebuilds everything. It runs from the arena folder (receipt-lab/arena/build), which has the font files for the other arena builds.

Tokens and the spec are in `docs/design/system/`.
