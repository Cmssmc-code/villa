"""Compare tracks DBMs: same keys and same pickled bytes per key; prints a fingerprint.

usage: python compare.py <reference dbm> <other dbm>...
"""
import dbm
import hashlib
import pickle
import sys


def digest(path):
    with dbm.open(path, 'r') as db:
        items = {k.decode() if isinstance(k, bytes) else k: bytes(db[k]) for k in db.keys()}
    h = hashlib.sha256()
    tracks = vertices = 0
    for k in sorted(items):
        h.update(k.encode() + b'\0' + items[k])
        t = pickle.loads(items[k])
        tracks += len(t)
        vertices += sum(len(a) for a in t)
    return items, h.hexdigest()[:16], tracks, vertices


ref, *others = sys.argv[1:]
r_items, r_fp, r_t, r_v = digest(ref)
print(f'{ref}: {len(r_items)} keys, {r_t} tracks, {r_v} vertices, fingerprint {r_fp}')
ok = True
for o in others:
    items, fp, t, v = digest(o)
    same = items == r_items
    ok &= same
    print(f'{o}: {len(items)} keys, {t} tracks, {v} vertices, fingerprint {fp}, '
          f'{"SAME keys and bytes" if same else "DIFFERENT"}')
print('RESULT', 'IDENTICAL' if ok else 'DIFFERENT')
