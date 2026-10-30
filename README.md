# Auldwyn Wardrobe

Plan Neverwinter Nights: EE armour outfits for the Auldwyn server outside the game, on a live 3D
character, then copy the share code into the in-game Wardrobe → Share tab (Import, then Apply).

## Run it

```sh
docker compose up -d web        # site on http://<server>:8086
```

The site is static: `web/index.html`, `web/data.js` and `web/3d/`. Any web host can serve that folder
as-is (it needs no server code).

## Rebuild after Auldwyn adds parts

1. Copy fresh game files from the PC into `gamefiles/`:
   - `gamefiles/data`: the NWN:EE install's `data` folder
   - `gamefiles/nwsync`: `Documents\Neverwinter Nights\nwsync`
2. Rebuild (about 90 seconds):

   ```sh
   docker compose run --rm build
   ```

This regenerates `web/data.js` (part lists and colour swatches) and `web/3d/` (models, textures,
palettes, skeletons). The web container picks up the new files straight away.

If Auldwyn's NWSync manifest changes, update `AULDWYN_MANIFEST` in `tools/nwnres.py`. The manifest whose
description is "Auldwyn NWSync" in `nwsyncmeta.sqlite3` is the right one.

## Share code

```json
{"c":"15,15,79,147,7,147","p":"4,4,8,8,4,4,154,1,63,153,16,16,5,5,7,7,6,6,0","t":167,"v":1}
```

- `c`: palette row (0–175) for Leather 1, Leather 2, Cloth 1, Cloth 2, Metal 1, Metal 2
- `p`: 19 part numbers in NWN's `ITEM_APPR_ARMOR_MODEL_*` order (right foot … robe)
- `t`: the visible torso. `p[7]` is passed through unchanged.

## Tools

| File | What it does |
| --- | --- |
| `tools/nwnres.py` | Reads base-game KEY/BIF archives and the NWSync databases (NWSync wins, like in-game) |
| `tools/mdl.py` | Reads binary and ASCII NWN models |
| `tools/build_data.py` | Writes `web/data.js` |
| `tools/build_3d.py` | Writes `web/3d/` |
| `tools/artifact_copy.py` | Base64 copies of the packs for hosts that only serve text files |
