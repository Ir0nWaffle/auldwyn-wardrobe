"""Read NWN models (binary and ASCII) into simple mesh lists.

Each model becomes a list of meshes. Every mesh has:
  name, texture, position/orientation of every ancestor node folded into
  a single model-space transform, and unwelded vertex arrays
  (positions, uvs, triangle indices).
Only what the wardrobe viewer needs is read: geometry, UVs, the texture name.
"""
import math
import struct

FLAG_MESH = 0x20
FLAG_SKIN = 0x40
FLAG_AABB = 0x200

CTRL_POSITION = 8
CTRL_ORIENTATION = 20


# ---------- small quaternion helpers (x, y, z, w) ----------
def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def q_rot(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    # v' = q * v * q^-1
    ix = w * vx + y * vz - z * vy
    iy = w * vy + z * vx - x * vz
    iz = w * vz + x * vy - y * vx
    iw = -x * vx - y * vy - z * vz
    return (ix * w + iw * -x + iy * -z - iz * -y,
            iy * w + iw * -y + iz * -x - ix * -z,
            iz * w + iw * -z + ix * -y - iy * -x)


def axis_angle(x, y, z, a):
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-9 or abs(a) < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    s = math.sin(a / 2) / n
    return (x * s, y * s, z * s, math.cos(a / 2))


class Node:
    def __init__(self, name):
        self.name = name
        self.parent = None
        self.pos = (0.0, 0.0, 0.0)
        self.rot = (0.0, 0.0, 0.0, 1.0)
        self.mesh = None  # dict(texture, verts, uvs, faces)
        self.kind = 'dummy'

    def world(self, nodes):
        """Transform from this node's space to the model root."""
        chain = []
        n = self
        while n is not None and n not in chain:  # guard against a node listed as its own ancestor
            chain.append(n)
            n = nodes.get(n.parent) if n.parent else None
        pos, rot = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)
        for n in reversed(chain):
            p = q_rot(rot, n.pos)
            pos = (pos[0] + p[0], pos[1] + p[1], pos[2] + p[2])
            rot = q_mul(rot, n.rot)
        return pos, rot


# ---------- binary ----------
def _cstr(b):
    return b.split(b'\0', 1)[0].decode('latin-1').lower()


def parse_binary(data):
    raw_off, _raw_size = struct.unpack_from('<II', data, 4)
    m = data[12:]
    raw = data[12 + raw_off:]
    root = struct.unpack_from('<I', m, 72)[0]
    nodes = {}
    seen = set()

    def arr(off):
        return struct.unpack_from('<III', m, off)  # offset, count, alloc

    def read(off, parent):
        name = _cstr(m[off + 32:off + 64])
        if name in nodes:  # some models reuse the root's name for the mesh
            name = f'{name}#{off}'
        flags = struct.unpack_from('<I', m, off + 108)[0]
        node = Node(name)
        node.parent = parent
        k_off, k_cnt, _ = arr(off + 84)
        d_off, d_cnt, _ = arr(off + 96)
        if k_cnt > 1000 or d_cnt > 100000 or off in seen:
            raise ValueError(f'bad node {name}')
        seen.add(off)
        floats = struct.unpack_from(f'<{d_cnt}f', m, d_off) if d_cnt else ()
        for i in range(k_cnt):
            ctype, rows, key_i, data_i, cols = struct.unpack_from('<ihhhB', m, k_off + i * 12)
            if ctype == CTRL_POSITION and cols >= 3:
                node.pos = tuple(floats[data_i:data_i + 3])
            elif ctype == CTRL_ORIENTATION and cols >= 4:
                node.rot = tuple(floats[data_i:data_i + 4])
        if flags & FLAG_MESH and not flags & FLAG_AABB:
            node.kind = 'skin' if flags & FLAG_SKIN else 'mesh'
            node.mesh = _binary_mesh(m, raw, off + 112)
        nodes[name] = node
        c_off, c_cnt, _ = arr(off + 72)
        for i in range(c_cnt):
            read(struct.unpack_from('<I', m, c_off + i * 4)[0], name)

    read(root, None)
    return nodes


def _binary_mesh(m, raw, h):
    f_off, f_cnt, _ = struct.unpack_from('<III', m, h + 8)
    render = struct.unpack_from('<I', m, h + 108)[0]
    texture = _cstr(m[h + 120:h + 184])
    v_ptr = struct.unpack_from('<I', m, h + 444)[0]
    v_cnt, _t_cnt = struct.unpack_from('<HH', m, h + 448)
    t0_ptr = struct.unpack_from('<I', m, h + 452)[0]
    if v_cnt == 0 or v_ptr == 0xFFFFFFFF or not render:
        return None
    if f_cnt > 200000 or v_ptr + v_cnt * 12 > len(raw):
        raise ValueError('bad mesh header')
    verts = list(struct.unpack_from(f'<{v_cnt * 3}f', raw, v_ptr))
    if t0_ptr != 0xFFFFFFFF:
        uvs = list(struct.unpack_from(f'<{v_cnt * 2}f', raw, t0_ptr))
    else:
        uvs = [0.0] * (v_cnt * 2)
    faces = []
    for i in range(f_cnt):
        faces.extend(struct.unpack_from('<HHH', m, f_off + i * 32 + 26))
    return {'texture': texture, 'verts': verts, 'uvs': uvs, 'faces': faces}


# ---------- ASCII ----------
def parse_ascii(text):
    nodes = {}
    lines = text.replace('\r', '').split('\n')
    i, n = 0, len(lines)
    in_geom = False
    cur = None
    while i < n:
        tok = lines[i].split()
        i += 1
        if not tok or tok[0].startswith('#'):
            continue
        k = tok[0].lower()
        if k == 'beginmodelgeom':
            in_geom = True
        elif k == 'endmodelgeom':
            in_geom = False
        elif not in_geom:
            continue
        elif k == 'node' and len(tok) >= 3:
            cur = Node(tok[2].lower())
            cur.kind = tok[1].lower()
            cur._m = {'verts': [], 'tverts': [], 'faces': [], 'texture': None, 'render': True}
        elif cur is None:
            continue
        elif k == 'endnode':
            md = cur._m
            if cur.kind in ('trimesh', 'danglymesh', 'skin') and md['verts'] and md['faces'] and md['render']:
                cur.mesh = _unweld(md)
            del cur._m
            nodes[cur.name] = cur
            cur = None
        elif k == 'parent':
            cur.parent = None if tok[1].lower() == 'null' else tok[1].lower()
        elif k == 'position':
            cur.pos = tuple(float(x) for x in tok[1:4])
        elif k == 'orientation':
            cur.rot = axis_angle(*(float(x) for x in tok[1:5]))
        elif k == 'bitmap':
            cur._m['texture'] = tok[1].lower()
        elif k == 'render':
            cur._m['render'] = tok[1] != '0'
        elif k in ('verts', 'tverts', 'faces', 'weights', 'constraints', 'colors', 'aabb'):
            if k == 'aabb' and len(tok) > 1:
                continue
            count = int(tok[1]) if len(tok) > 1 else 0
            rows = lines[i:i + count]
            i += count
            # Some exporters write fewer rows than the count says; stop at the first non-number row.
            parsed = []
            for j, r in enumerate(rows):
                p = r.split()
                try:
                    if k == 'verts':
                        parsed.append(tuple(float(x) for x in p[:3]))
                    elif k == 'tverts':
                        parsed.append(tuple(float(x) for x in p[:2]))
                    elif k == 'faces':
                        parsed.append((int(p[0]), int(p[1]), int(p[2]), int(p[4]), int(p[5]), int(p[6])))
                    else:
                        parsed.append(None)
                except (ValueError, IndexError):
                    i -= count - j  # re-read the rest as normal lines
                    break
            if k == 'verts':
                cur._m['verts'] = parsed
            elif k == 'tverts':
                cur._m['tverts'] = parsed
            elif k == 'faces':
                nv, nt = len(cur._m['verts']), len(cur._m['tverts'])
                cur._m['faces'] = [f for f in parsed if max(f[:3]) < nv]
    return nodes


def _unweld(md):
    verts, tverts = md['verts'], md['tverts']
    out_v, out_uv, out_f, seen = [], [], [], {}
    for v0, v1, v2, t0, t1, t2 in md['faces']:
        for v, t in ((v0, t0), (v1, t1), (v2, t2)):
            key = (v, t)
            idx = seen.get(key)
            if idx is None:
                idx = len(out_v) // 3
                seen[key] = idx
                out_v.extend(verts[v])
                out_uv.extend(tverts[t] if t < len(tverts) else (0.0, 0.0))
            out_f.append(idx)
    return {'texture': md['texture'], 'verts': out_v, 'uvs': out_uv, 'faces': out_f}


def parse(data):
    if data[:4] == b'\0\0\0\0':
        return parse_binary(data)
    return parse_ascii(data.decode('latin-1'))


def meshes(data):
    """All renderable meshes of a model, with vertices moved into model space."""
    nodes = parse(data)
    out = []
    for node in nodes.values():
        if not node.mesh:
            continue
        pos, rot = node.world(nodes)
        v = node.mesh['verts']
        world = []
        for j in range(0, len(v), 3):
            p = q_rot(rot, (v[j], v[j + 1], v[j + 2]))
            world.extend((p[0] + pos[0], p[1] + pos[1], p[2] + pos[2]))
        out.append({'name': node.name, 'kind': node.kind, 'texture': node.mesh['texture'],
                    'verts': world, 'uvs': node.mesh['uvs'], 'faces': node.mesh['faces']})
    return out


def skeleton(data):
    """Model-space position of every node (rest pose)."""
    nodes = parse(data)
    return {name: n.world(nodes)[0] for name, n in nodes.items()}


def parents(data):
    nodes = parse(data)
    return {name: n.parent for name, n in nodes.items()}
