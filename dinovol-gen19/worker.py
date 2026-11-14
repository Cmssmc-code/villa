"""Worker started by verifier.py inside a Windows job object with a memory limit. Not meant to be run by hand.

  worker.py build   <code_dir> <catalogue.json> <config.json> <cache_dir> <out.json> <banded|unbanded>
  worker.py measure <code_dir> <cache_dir> <volume.json> <out.json> <sample.npz>

<code_dir> is an export of the dinovol folder (it contains dinovol_2/). Everything that decides what is
cached is the real dinovol code of that export: the real command `python -m dinovol_2.cache_metadata_meshes`
(its main()), which calls the real load_or_build_volume_meshes, which picks the representation and the
coordinate scale of each segment, reads x.tif, y.tif and z.tif over the network with the real reader, and
writes the real .npz cache.

The only thing replaced is how build_mesh_segment_from_arrays is called ("banded" mode): it is called on
slices of rows of the three arrays instead of on the whole arrays, because the whole-array call needs more
than 3.5 GB for this 56913 x 956 mesh (the "unbanded" mode shows it). The function works point by point, so
the result is identical; the first call checks that on a small block, with the real function on both sides.
"""
import json
import sys
import tempfile
import time

import numpy as np

mode, code_dir = sys.argv[1], sys.argv[2]
sys.path.insert(0, code_dir)
sys.dont_write_bytecode = True
import dinovol_2.cache_metadata_meshes as cmm  # noqa: E402
import dinovol_2.dataset.object_labels as ol  # noqa: E402

BAND_ROWS = 64


def peak_gb():
    """Peak committed memory of this process so far (Windows PROCESS_MEMORY_COUNTERS_EX)."""
    import ctypes
    import ctypes.wintypes as wt

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [(n, ctypes.c_size_t) for n in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(pmc)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wt.HANDLE
    ctypes.WinDLL("psapi").GetProcessMemoryInfo(wt.HANDLE(k32.GetCurrentProcess()), ctypes.byref(pmc), pmc.cb)
    return pmc.PeakPagefileUsage / 1e9


def log(text):
    print(f"[peak {peak_gb():.2f} GB] {text}", flush=True)


def build(catalogue, config, cache_dir, out, how):
    info = dict(mode=how, builds=[], tiff_urls=[], selected_shapes=[])
    real_build = ol.build_mesh_segment_from_arrays
    real_read = ol._read_tiff
    real_load = cmm.load_or_build_volume_meshes
    checked = []

    def read_tiff(url, storage_options=None):
        info["tiff_urls"].append(str(url))
        t0 = time.time()
        arr = real_read(url, storage_options)
        log(f"read {url.split('/segments/')[-1]} {arr.shape} {arr.dtype} in {time.time() - t0:.0f} s")
        return arr

    def banded(seg_id, x, y, z, scale0_shape=None, selected_shape=None, *, transform_matrix=None,
               coordinate_scale=1.0, inklabels=None, supervision=None):
        kw = dict(transform_matrix=transform_matrix, coordinate_scale=coordinate_scale)
        info["builds"].append(dict(
            segment_id=seg_id, coordinate_scale=float(coordinate_scale),
            has_transform_matrix=transform_matrix is not None, scale0_shape=list(scale0_shape),
            selected_shape=list(selected_shape), shape=list(x.shape)))
        log(f"build {seg_id}: coordinate_scale={coordinate_scale}, transform={transform_matrix is not None}, "
            f"arrays {x.shape} {x.dtype}, scale0_shape={tuple(scale0_shape)}, selected_shape={tuple(selected_shape)}")
        if how == "unbanded" or inklabels is not None or supervision is not None:
            log("calling the real build_mesh_segment_from_arrays on the whole arrays")
            return real_build(seg_id, x, y, z, scale0_shape, selected_shape, inklabels=inklabels,
                              supervision=supervision, **kw)
        h, w = x.shape

        def one(r0, r1):
            return real_build(seg_id, x[r0:r1], y[r0:r1], z[r0:r1], scale0_shape, selected_shape, **kw)

        if not checked:  # the banded result equals the whole-array result, on a block of 24 rows
            b0 = h // 2
            whole, parts = one(b0, b0 + 24), [one(r, r + 6) for r in range(b0, b0 + 24, 6)]
            zyx = np.full((24, w, 3), np.nan, dtype=np.float32)
            valid = np.zeros((24, w), dtype=bool)
            for k, p in enumerate(parts):
                if p is not None:
                    zyx[k * 6:(k + 1) * 6], valid[k * 6:(k + 1) * 6] = p.zyx, p.valid
            same = (whole is not None and np.array_equal(zyx, whole.zyx, equal_nan=True)
                    and np.array_equal(valid, whole.valid)
                    and np.array_equal(np.minimum.reduce([p.bbox_lo for p in parts if p is not None]), whole.bbox_lo)
                    and np.array_equal(np.maximum.reduce([p.bbox_hi for p in parts if p is not None]), whole.bbox_hi))
            checked.append(same)
            info["banded_equals_whole_on_24_rows"] = bool(same)
            log(f"banded call equals whole-array call on 24 rows ({int(valid.sum()):,} points): {same}")
            del whole, parts, zyx, valid
        # The result lives in a file-backed memory map (in the work folder), not in committed memory: it is
        # 653 MB, and the real save function makes one more full copy of it in memory.
        out_zyx = np.memmap(tempfile.mktemp(prefix="zyx-", suffix=".bin"), dtype=np.float32, mode="w+",
                            shape=(h, w, 3))
        out_zyx[:] = np.nan
        out_valid = np.zeros((h, w), dtype=bool)
        lo, hi = np.full(3, np.inf, dtype=np.float32), np.full(3, -np.inf, dtype=np.float32)
        for r0 in range(0, h, BAND_ROWS):
            r1 = min(r0 + BAND_ROWS, h)
            seg = one(r0, r1)
            if seg is None:
                continue
            out_zyx[r0:r1], out_valid[r0:r1] = seg.zyx, seg.valid
            lo, hi = np.minimum(lo, seg.bbox_lo), np.maximum(hi, seg.bbox_hi)
        log(f"banded build done ({h} rows in slices of {BAND_ROWS})")
        if not out_valid.any():
            return None
        res = ol.MeshSegment(segment_id=str(seg_id), zyx=out_zyx, valid=out_valid,
                             ink_state=np.zeros((h, w), dtype=np.int8), bbox_lo=lo, bbox_hi=hi, has_ink=False)
        res.ensure_spatial_index()
        return res

    def load(*a, **k):
        info["selected_shapes"].append(list(a[2]))
        res = real_load(*a, **k)
        info["n_meshes"] = len(res)
        return res

    ol._read_tiff, ol.build_mesh_segment_from_arrays, cmm.load_or_build_volume_meshes = read_tiff, banded, load
    sys.argv = ["cache_metadata_meshes", "--config", config, "--metadata", catalogue, "--cache-dir", cache_dir]
    t0 = time.time()
    cmm.main()
    log("cmm.main() finished (mesh built, .npz written)")
    info["seconds"] = time.time() - t0
    json.dump(info, open(out, "w"), indent=1)


def measure(cache_dir, volume_json, out, sample_out):
    vol = json.load(open(volume_json, encoding="utf-8"))
    cache = f"{cache_dir}/PHercParis4_{vol['volume_id']}_scale{vol['volume_scale']}.npz"
    segs = ol.load_mesh_segments_cache(cache)
    log(f"{cache.rsplit('/', 1)[-1]}: {len(segs)} mesh(es)")
    seg = segs[0]
    chunk = np.array(vol["chunks"])
    grid = np.array([-(-s // c) for s, c in zip(vol["level4_shape"], chunk)])
    present = np.array(sorted(((z * grid[1] + y) * grid[2] + x) for z, y, x in vol["present_level4"]),
                       dtype=np.int64)
    ratio = 2 ** (4 - vol["volume_scale"])  # selected level -> level 4
    n = hit = 0
    for r0 in range(0, seg.valid.shape[0], 64):
        pts = seg.zyx[r0:r0 + 64][seg.valid[r0:r0 + 64]].astype(np.float64)
        c = np.floor(pts / ratio / chunk).astype(np.int64)
        inside = np.all((c >= 0) & (c < grid), axis=1)
        key = (c[:, 0] * grid[1] + c[:, 1]) * grid[2] + c[:, 2]
        n += len(pts)
        hit += int((np.isin(key, present) & inside).sum())
    rows, cols = np.nonzero(seg.valid[::7, ::211])
    np.savez(sample_out, rc=np.stack([rows * 7, cols * 211], axis=1), zyx=seg.zyx[::7, ::211][rows, cols])
    res = dict(segment_id=seg.segment_id, grid_shape=list(seg.valid.shape), valid_points=n,
               points_in_existing_level4_chunk=hit, bbox_lo_zyx=seg.bbox_lo.tolist(),
               bbox_hi_zyx=seg.bbox_hi.tolist(), n_meshes=len(segs))
    json.dump(res, open(out, "w"), indent=1)
    log(json.dumps(res))


if mode == "build":
    build(*sys.argv[3:8])
else:
    measure(*sys.argv[3:7])
