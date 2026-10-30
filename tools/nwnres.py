"""Read NWN:EE resources from the base game (KEY/BIF) and an NWSync manifest.

NWSync content overrides base game content, the same way the game loads it.
"""
import os
import sqlite3
import struct
from compression import zstd
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOT = os.environ.get('GAMEFILES', os.path.join(PROJECT, 'gamefiles'))
AULDWYN_MANIFEST = 'aa12e719c1bc2701a33f7836f628b30cde8a43d3'

RESTYPES = {3: 'tga', 6: 'plt', 2002: 'mdl', 2017: '2da', 2033: 'dds', 2036: 'mtr', 2022: 'txi'}
EXT_TO_TYPE = {v: k for k, v in RESTYPES.items()}


def _decompress(blob):
    # NWSync "NSYC" container: magic, version, algorithm, uncompressed size,
    # then for zstd two more uint32s (header version, dictionary) before the frame.
    if blob[:4] != b'NSYC':
        return blob
    _ver, algo, size = struct.unpack_from('<III', blob, 4)
    if algo == 0:
        return blob[16:]
    if algo == 2:
        return zstd.decompress(blob[24:])
    raise ValueError(f'unsupported NWSync compression {algo}')


class Base:
    """Base game resources indexed from data/*.key."""

    def __init__(self, data_dir=os.path.join(ROOT, 'data')):
        self.data_dir = data_dir
        self.index = {}  # (resref, restype) -> (bif path, resource index)
        for key in ('nwn_base.key', 'nwn_retail.key'):
            self._load_key(os.path.join(data_dir, key))

    def _load_key(self, path):
        b = open(path, 'rb').read()
        nbif, nkey, off_files, off_keys = struct.unpack_from('<IIII', b, 8)
        bifs = []
        for i in range(nbif):
            _size, noff, nlen, _drv = struct.unpack_from('<IIHH', b, off_files + i * 12)
            name = b[noff:noff + nlen].rstrip(b'\0').decode().replace('\\', '/')
            bifs.append(os.path.join(self.data_dir, os.path.basename(name)))
        for i in range(nkey):
            o = off_keys + i * 22
            resref = b[o:o + 16].rstrip(b'\0').decode('latin-1').lower()
            restype, resid = struct.unpack_from('<HI', b, o + 16)
            self.index[(resref, restype)] = (bifs[resid >> 20], resid & 0xFFFFF)

    def get(self, resref, restype):
        hit = self.index.get((resref, restype))
        if not hit:
            return None
        path, idx = hit
        with open(path, 'rb') as f:
            _t, _v, nvar, _nfix, off = struct.unpack('<4s4sIII', f.read(20))
            f.seek(off + idx * 16)
            _id, roff, rsize, _rt = struct.unpack('<IIII', f.read(16))
            f.seek(roff)
            return f.read(rsize)


class NWSync:
    def __init__(self, manifest=AULDWYN_MANIFEST, nwsync_dir=os.path.join(ROOT, 'nwsync')):
        meta = sqlite3.connect(f'file:{nwsync_dir}/nwsyncmeta.sqlite3?mode=ro', uri=True)
        self.index = {}
        for resref, restype, sha1 in meta.execute(
                'select resref, restype, resref_sha1 from manifest_resrefs where manifest_sha1=?', (manifest,)):
            self.index[(resref.lower(), restype)] = sha1
        self.shards = [sqlite3.connect(f'file:{p}?mode=ro', uri=True)
                       for p in sorted(os.path.join(nwsync_dir, n) for n in os.listdir(nwsync_dir)
                                       if n.startswith('nwsyncdata_') and n.endswith('.sqlite3'))]

    def get(self, resref, restype):
        sha1 = self.index.get((resref, restype))
        if not sha1:
            return None
        for db in self.shards:
            row = db.execute('select data from resrefs where sha1=?', (sha1,)).fetchone()
            if row:
                return _decompress(row[0])
        return None


class Resources:
    """Combined lookup: Auldwyn NWSync first, then the base game."""

    def __init__(self):
        self.nwsync = NWSync()
        self.base = Base()

    def get(self, resref, ext):
        restype = EXT_TO_TYPE[ext]
        resref = resref.lower()
        return self.nwsync.get(resref, restype) or self.base.get(resref, restype)

    def names(self, ext):
        restype = EXT_TO_TYPE[ext]
        return {r for (r, t) in list(self.nwsync.index) + list(self.base.index) if t == restype}

    def source(self, resref, ext):
        key = (resref.lower(), EXT_TO_TYPE[ext])
        return 'auldwyn' if key in self.nwsync.index else 'base' if key in self.base.index else None


def parse_2da(data):
    lines = [l for l in data.decode('latin-1').splitlines()]
    body = [l for l in lines[1:] if l.strip() and not l.strip().startswith('DEFAULT')]
    import shlex
    cols = shlex.split(body[0])
    rows = {}
    for l in body[1:]:
        parts = shlex.split(l)
        if not parts:
            continue
        rows[int(parts[0])] = dict(zip(cols, parts[1:]))
    return cols, rows
