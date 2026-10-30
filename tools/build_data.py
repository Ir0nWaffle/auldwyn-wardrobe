"""Extract part lists and colour palettes into web/data.js for the wardrobe page."""
import json
import os
import re
import struct
from collections import defaultdict

import nwnres
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUT = os.path.join(PROJECT, 'web', 'data.js')

# Share-code part order (matches NWN's ITEM_APPR_ARMOR_MODEL_* constants).
SLOTS = [
    ('footr', 'Right Foot'), ('footl', 'Left Foot'),
    ('shinr', 'Right Shin'), ('shinl', 'Left Shin'),
    ('legl', 'Left Thigh'), ('legr', 'Right Thigh'),
    ('pelvis', 'Pelvis'), ('chest', 'Torso'), ('belt', 'Belt'), ('neck', 'Neck'),
    ('forer', 'Right Forearm'), ('forel', 'Left Forearm'),
    ('bicepr', 'Right Bicep'), ('bicepl', 'Left Bicep'),
    ('shor', 'Right Shoulder'), ('shol', 'Left Shoulder'),
    ('handr', 'Right Hand'), ('handl', 'Left Hand'),
    ('robe', 'Robe'),
]
RACES = [('h', 'Human / Half-elf'), ('e', 'Elf'), ('d', 'Dwarf'), ('g', 'Gnome'),
         ('a', 'Halfling'), ('o', 'Half-orc')]
PHENOS = [('0', 'Normal'), ('2', 'Large')]
PALETTES = [('leath', 'pal_leath01'), ('cloth', 'pal_cloth01'),
            ('metal1', 'pal_armor01'), ('metal2', 'pal_armor02'),
            ('skin', 'pal_skin01'), ('hair', 'pal_hair01')]
# Palette columns sampled for each swatch: bright centre fading to a darker edge.
SWATCH_COLS = (245, 200, 140, 70)


def read_palette(data):
    idl = data[0]
    w, h, bpp, desc = struct.unpack_from('<HHBB', data, 12)
    assert data[2] == 2 and bpp == 32 and (w, h) == (256, 176)
    px = data[18 + idl:]
    rows = []
    for row in range(h):
        y = row if desc & 0x20 else h - 1 - row
        stops = []
        for col in SWATCH_COLS:
            o = (y * w + col) * 4
            b, g, r = px[o], px[o + 1], px[o + 2]
            stops.append('%02x%02x%02x' % (r, g, b))
        rows.append(stops)
    return rows


def load_excluded():
    """Parts the tool never offers or ships (see excluded_parts.json)."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'excluded_parts.json')) as f:
        return {k: set(v) for k, v in json.load(f).items() if not k.startswith('_')}


def main():
    excluded = load_excluded()
    res = nwnres.Resources()
    pat = re.compile(r'^p([mf])([a-z])(\d)_([a-z]+?)(\d{3})$')
    parts = defaultdict(lambda: defaultdict(set))
    base_nums = defaultdict(set)  # slot -> part numbers the base game has for any body
    for (name, restype) in res.base.index:
        m = restype == 2002 and pat.match(name)
        if m:
            base_nums[m.group(4)].add(int(m.group(5)))
    custom = defaultdict(set)  # slot -> part numbers only Auldwyn adds
    for name in res.names('mdl'):
        m = pat.match(name)
        if not m:
            continue
        g, r, ph, slot, num = m.groups()
        parts[g + r + ph][slot].add(int(num))
        if int(num) not in base_nums[slot]:
            custom[slot].add(int(num))

    models = {}
    for g in 'mf':
        for r, _ in RACES:
            for ph, _ in PHENOS:
                key = g + r + ph
                models[key] = {s: sorted((parts[key][s] | {0}) - excluded.get(s, set())) for s, _ in SLOTS}

    data = {
        'slots': [{'id': s, 'name': n} for s, n in SLOTS],
        'races': [{'id': r, 'name': n} for r, n in RACES],
        'phenotypes': [{'id': p, 'name': n} for p, n in PHENOS],
        'models': models,
        'custom': {s: sorted(v - excluded.get(s, set())) for s, v in sorted(custom.items())},
        'excluded': {s: sorted(v) for s, v in sorted(excluded.items())},
        'palettes': {k: read_palette(res.get(p, 'tga')) for k, p in PALETTES},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        f.write('window.WARDROBE_DATA = ')
        json.dump(data, f, separators=(',', ':'))
        f.write(';\n')
    print('wrote', OUT, os.path.getsize(OUT), 'bytes')
    fe = models['fe0']
    print({s: len(v) for s, v in fe.items()})


if __name__ == '__main__':
    main()
