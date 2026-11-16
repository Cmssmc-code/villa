"""Compare tracks stores key by key and value by value. usage: python cmp.py <a.dbm> <b.dbm>"""
import dbm
import hashlib
import sys

out = []
for p in sys.argv[1:]:
    with dbm.open(p, 'r') as db:
        d = {bytes(k): bytes(db[k]) for k in db.keys()}
    h = hashlib.sha256()
    for k in sorted(d):
        h.update(k + b'\0' + d[k] + b'\1')
    out.append(d)
    print(f'{p}: {len(d)} keys sha256={h.hexdigest()[:16]}')
print('IDENTICAL' if all(o == out[0] for o in out) else 'DIFFERENT')
