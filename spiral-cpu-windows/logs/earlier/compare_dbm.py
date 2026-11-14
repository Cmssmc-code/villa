"""Compare two tracks DBMs key by key: same keys, same pickled bytes, and same set of tracks.

usage: python compare_dbm.py <a.dbm> <b.dbm>
"""
import dbm
import hashlib
import pickle
import sys


def load(path):
    with dbm.open(path, 'r') as db:
        return {k.decode(): db[k] for k in db.keys()}


a, b = load(sys.argv[1]), load(sys.argv[2])
print(f'{sys.argv[1]}: {len(a)} keys; {sys.argv[2]}: {len(b)} keys')
print('same keys:', a.keys() == b.keys())
common = sorted(a.keys() & b.keys())
same_bytes = sum(a[k] == b[k] for k in common)
canon = lambda raw: sorted(t.tolist() for t in pickle.loads(raw))
diff = [k for k in common if canon(a[k]) != canon(b[k])]
n_tracks = sum(len(pickle.loads(a[k])) for k in common)
n_vertices = sum(len(t) for k in common for t in pickle.loads(a[k]))
print(f'keys with identical pickled bytes: {same_bytes}/{len(common)}')
print(f'keys with identical track sets: {len(common) - len(diff)}/{len(common)}; differing: {diff[:10]}')
print(f'tracks: {n_tracks}, vertices: {n_vertices}')
h = hashlib.sha256()
for k in common:
    h.update(k.encode())
    h.update(repr(canon(a[k])).encode())
print('fingerprint of sorted track sets (a):', h.hexdigest()[:16])
sys.exit(0 if a.keys() == b.keys() and not diff else 1)
