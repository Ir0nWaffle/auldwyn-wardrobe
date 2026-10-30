"""Convert part models, heads and colour textures into packs the 3D viewer loads.

Output (web/3d/):
  index.json            what is in every pack
  body_<prefix>.bin     every part + head mesh for one body (e.g. fe0), gzip
  tex_<n>.bin           colour-layer textures, gzip, ~1.5 MB each
  palettes.bin          10 palettes stacked (256 x 1760 RGBA), gzip

Mesh vertices are moved into body space here, so the viewer just draws them.
"""
import gzip
import json
import math
import os
import re
import struct
import sys
from collections import defaultdict

import nwnres
import mdl
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUT = os.path.join(PROJECT, 'web', '3d')
DATA = os.path.join(PROJECT, 'web', 'data.js')
MAX_TEX = 256          # textures are downscaled to at most this size
CHUNK_RAW = 4_000_000  # raw bytes per texture pack before gzip
POS_SCALE = 8192       # int16 position = metres * POS_SCALE
UV_SCALE = 4096        # int16 uv = uv * UV_SCALE

ATTACH = {
    'chest': 'torso_g', 'pelvis': 'pelvis_g', 'belt': 'belt_g', 'neck': 'neck_g', 'head': 'head_g',
    'shol': 'lshoulder_g', 'shor': 'rshoulder_g', 'bicepl': 'lbicep_g', 'bicepr': 'rbicep_g',
    'forel': 'lforearm_g', 'forer': 'rforearm_g', 'handl': 'lhand_g', 'handr': 'rhand_g',
    'legl': 'lthigh_g', 'legr': 'rthigh_g', 'shinl': 'lshin_g', 'shinr': 'rshin_g',
    'footl': 'lfoot_g', 'footr': 'rfoot_g',
    'helm': 'head_g', 'cloak': '',
}
# appearance.2da rows of the playable races, by model letter (half-elves use the human model).
RACE_ROW = {'d': 0, 'e': 1, 'g': 2, 'a': 3, 'o': 5, 'h': 6}
# Palette rows stacked in PLT layer order.
PALETTES = ['pal_skin01', 'pal_hair01', 'pal_armor01', 'pal_armor02', 'pal_cloth01', 'pal_cloth01',
            'pal_leath01', 'pal_leath01', 'pal_tattoo01', 'pal_tattoo01']


class Textures:
    def __init__(self, res):
        self.res = res
        self.ids = {}     # resolved PLT name -> id
        self.order = []   # id -> PLT name
        self.cache = {}   # requested name -> id or -1

    def resolve(self, name):
        if not name:
            return None
        if name in self.cache:
            return self.cache[name]
        cands = [name]
        if re.match(r'^p[mf][a-z]\d_', name):
            cands += [name[:2] + 'h' + name[3:], name[:3] + '0' + name[4:], name[:2] + 'h0' + name[4:]]
        tid = -1
        for c in cands:
            if self.res.get(c, 'plt'):
                if c not in self.ids:
                    self.ids[c] = len(self.order)
                    self.order.append(c)
                tid = self.ids[c]
                break
        self.cache[name] = tid
        return tid

    def pack(self):
        """Write texture packs; return [chunk, offset, w, h] per texture id."""
        table, chunk, buf, n = [], [], 0, 0

        def flush():
            nonlocal chunk, buf, n
            if not chunk:
                return
            write_gz(f'tex_{n}.bin', b''.join(chunk))
            n += 1
            chunk, buf = [], 0

        for name in self.order:
            p = self.res.get(name, 'plt')
            w, h = struct.unpack_from('<II', p, 16)
            px = p[24:24 + w * h * 2]
            step = max(1, max(w, h) // MAX_TEX)
            if step > 1:
                rows = []
                for y in range(0, h, step):
                    row = px[y * w * 2:(y + 1) * w * 2]
                    rows.append(b''.join(row[x * 2:x * 2 + 2] for x in range(0, w, step)))
                px, w, h = b''.join(rows), len(range(0, w, step)), len(range(0, h, step))
            # Planar layout: shade deltas, then layer ids (compresses ~30% better).
            v, layer = px[0::2], px[1::2]
            delta = bytes((v[i] - (v[i - 1] if i else 0)) & 255 for i in range(len(v)))
            px = delta + layer
            if buf + len(px) > CHUNK_RAW:
                flush()
            table.append([n, buf, w, h])
            chunk.append(px)
            buf += len(px)
        flush()
        return table, n


def write_gz(name, data):
    with open(os.path.join(OUT, name), 'wb') as f:
        f.write(gzip.compress(data, 9, mtime=0))


def smooth_normals(verts, faces):
    """Per-vertex normals averaged over all faces sharing a position (ignores UV seams)."""
    key = lambda i: (round(verts[i * 3] * 2000), round(verts[i * 3 + 1] * 2000), round(verts[i * 3 + 2] * 2000))
    acc = defaultdict(lambda: [0.0, 0.0, 0.0])
    for t in range(0, len(faces), 3):
        a, b, c = faces[t:t + 3]
        ax, ay, az = verts[a * 3:a * 3 + 3]
        bx, by, bz = verts[b * 3:b * 3 + 3]
        cx, cy, cz = verts[c * 3:c * 3 + 3]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        for i in (a, b, c):
            s = acc[key(i)]
            s[0] += n[0]; s[1] += n[1]; s[2] += n[2]
    out = []
    for i in range(len(verts) // 3):
        x, y, z = acc[key(i)]
        l = math.sqrt(x * x + y * y + z * z) or 1.0
        out.extend((x / l, y / l, z / l))
    return out


def clamp16(v):
    return max(-32768, min(32767, int(round(v))))


def build_body(res, tex, prefix, part_lists, heads, helms, cloaks):
    """Pack every mesh of one body. Returns (bytes, index)."""

    blob = bytearray()
    index = defaultdict(dict)
    failed = []

    def add(slot, num, name, texture=None):
        data = res.get(name, 'mdl')
        if not data:
            return
        try:
            meshes = mdl.meshes(data)
        except Exception as e:  # damaged model: show nothing for it
            failed.append(f'{name}: {e}')
            return
        out = []
        for m in meshes:
            tid = tex.resolve(texture or m['texture'])
            if tid is None:        # blank texture: deliberately invisible piece
                continue
            # Vertices stay relative to the bone they hang from; the viewer places the bone.
            if slot == 'robe':
                low = min(m['verts'][2::3])
                bone = '' if (m['kind'] == 'skin' or low > 0.05) else 'torso_g'
            else:
                bone = ATTACH[slot]
            moved = m['verts']
            normals = smooth_normals(moved, m['faces'])
            vc, ic = len(moved) // 3, len(m['faces'])
            if vc > 65535:
                continue
            start = len(blob)
            blob.extend(struct.pack(f'<{vc * 3}h', *(clamp16(x * POS_SCALE) for x in moved)))
            blob.extend(struct.pack(f'<{vc * 2}h', *(clamp16(x * UV_SCALE) for x in m['uvs'])))
            blob.extend(struct.pack(f'<{vc * 3}b', *(max(-127, min(127, int(round(x * 127)))) for x in normals)))
            if len(blob) % 2:
                blob.append(0)
            blob.extend(struct.pack(f'<{ic}H', *m['faces']))
            if len(blob) % 4:
                blob.extend(b'\0' * (4 - len(blob) % 4))
            out.append([start, vc, ic, tid, bone])
        if out:
            index[slot][num] = out

    for slot, nums in part_lists.items():
        for num in nums:
            if num:
                add(slot, num, f'p{prefix}_{slot}{num:03d}')
    for num in heads:
        add('head', num, f'p{prefix}_head{num:03d}')
    for num in helms:
        add('helm', num, f'helm_{num:03d}')
    for num, (model, texture) in cloaks.items():
        add('cloak', num, f'p{prefix}_cloak_{model:03d}', f'cloak_{texture:03d}')
    return bytes(blob), index, failed


def build_skeleton(res, prefix):
    """Bones the parts hang from: name -> [parent bone, x, y, z] in model space (rest pose)."""
    data = res.get('p' + prefix, 'mdl')
    world, parent = mdl.skeleton(data), mdl.parents(data)
    keep = set(ATTACH.values())
    for name in list(keep):  # include every ancestor so the chain is complete
        n = parent.get(name)
        while n and n in world:
            keep.add(n)
            n = parent.get(n)
    out = {}
    for name in sorted(keep):
        if name not in world:
            continue
        p = parent.get(name)
        while p and p not in keep:
            p = parent.get(p)
        out[name] = [p or ''] + [round(x, 5) for x in world[name]]
    return out


def build_palettes(res):
    rows = []
    for name in PALETTES:
        b = res.get(name, 'tga')
        idl = b[0]
        w, h, bpp, desc = struct.unpack_from('<HHBB', b, 12)
        px = b[18 + idl:]
        for row in range(h):
            y = row if desc & 0x20 else h - 1 - row
            line = bytearray()
            for x in range(w):
                o = (y * w + x) * 4
                line += bytes((px[o + 2], px[o + 1], px[o], 255))
            rows.append(bytes(line))
    write_gz('palettes.bin', b''.join(rows))


def main():
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[1:]  # optional: build just these bodies, e.g. fe0
    res = nwnres.Resources()
    data = json.loads(open(DATA).read().split('= ', 1)[1].rstrip(';\n'))
    tex = Textures(res)
    head_re = re.compile(r'^p([mf][a-z]\d)_head(\d{3})$')
    heads = defaultdict(set)
    for name in res.names('mdl'):
        m = head_re.match(name)
        if m:
            heads[m.group(1)].add(int(m.group(2)))

    robe_hide = {}
    cols, rows = nwnres.parse_2da(res.get('parts_robe', '2da'))
    for num, r in rows.items():
        hide = [c[4:].lower() for c in cols if c.startswith('HIDE') and r.get(c) == '1']
        if hide:
            robe_hide[num] = hide

    # Helmets: one shared set (helm_###), scaled per race and gender like the game does.
    helms = sorted(int(n[5:]) for n in res.names('mdl') if re.match(r'^helm_\d{3}$', n))
    _, app = nwnres.parse_2da(res.get('appearance', '2da'))
    helm_scale = {}
    for g in 'mf':
        for race, row in RACE_ROW.items():
            v = app[row].get('HELMET_SCALE_' + g.upper(), '1')
            helm_scale[g + race] = float(v) if v != '****' else 1.0
    # Cloaks: cloakmodel.2da picks a model shape and a texture; some hide the shoulder pads.
    ccols, crows = nwnres.parse_2da(res.get('cloakmodel', '2da'))
    cloaks, cloak_info = {}, {}
    for num, r in crows.items():
        if num and r.get('MODEL', '****') not in ('****', '0'):
            cloaks[num] = (int(r['MODEL']), int(r['TEXTURE']))
            hide = [side for side, col in (('shol', 'HIDESHOL'), ('shor', 'HIDESHOR')) if r.get(col) == '1']
            cloak_info[num] = {'name': r.get('LABEL', '').replace('_', ' '), 'hide': hide}

    index = {'posScale': POS_SCALE, 'uvScale': UV_SCALE, 'bodies': {}, 'heads': {}, 'skeletons': {}, 'robeHide': robe_hide,
             'helms': {}, 'helmScale': helm_scale, 'cloaks': {}, 'cloakInfo': cloak_info}
    for prefix, parts in data['models'].items():
        if only and prefix not in only:
            continue
        blob, idx, failed = build_body(res, tex, prefix, parts, sorted(heads[prefix]), helms, cloaks)
        write_gz(f'body_{prefix}.bin', blob)
        index['bodies'][prefix] = idx
        index['skeletons'][prefix] = build_skeleton(res, prefix)
        index['heads'][prefix] = sorted(int(k) for k in idx.get('head', {}))
        index['helms'][prefix] = sorted(int(k) for k in idx.get('helm', {}))
        index['cloaks'][prefix] = sorted(int(k) for k in idx.get('cloak', {}))
        print(prefix, f'{len(blob) / 1e6:.1f} MB raw', f'{len(idx.get("head", {}))} heads', f'{len(failed)} failed', failed[:2])
    index['textures'], index['texPacks'] = tex.pack()
    build_palettes(res)
    with open(os.path.join(OUT, 'index.json'), 'w') as f:
        json.dump(index, f, separators=(',', ':'))
    total = sum(os.path.getsize(os.path.join(OUT, n)) for n in os.listdir(OUT))
    print('textures', len(tex.order), 'packs', index['texPacks'], f'total {total / 1e6:.1f} MB on disk')


if __name__ == '__main__':
    main()
