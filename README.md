Proof files (screenshots, scripts and logs) for pull requests to ScrollPrize/villa.

- `catalog-cache/`: VC3D's Open Data catalog on Windows. `vc3d_catalog.py` imports `../outils/capture_console.py`.
- `url-port/`: a remote volume whose URL has a port, on Windows.
- `dinovol-gzip/`: dinovol reading `metadata.json` when the bucket serves it gzip-compressed.
- `vc3d-long-paths/`: VC3D tools on Windows with paths longer than 260 characters.
- `vc3d-tutorial-windows/`: The VC3D tutorial's Windows instructions, checked against the released files.
- `spiral-cpu-windows/`: spiral-fitting's CPU track extraction on Windows (and Linux/macOS CI runs).
- `dinovol-gen19/`: dinovol's cached mesh for PHercParis4 `20260926044226-spiral-output-generation-19` (issue evidence).
- `vc3d-packaging/`: VC3D packaging (cpack) on Windows after the fiber tools were added to the build.
- `vc3d-old-project-stores/`: VC3D opening a project whose object store has the previous schema.
- `vc3d-local-volume/`: VC3D opening a volume downloaded as is from the open-data bucket.
- `vc3d-export-grown-segment/`: Exporting a segment grown from a seed in VC3D.
- `vc3d-exit-hang-windows/`: VC3D tools built from main that never exit on Windows after their work is done (issue evidence).
- `vc3d-appimage-builder/`: The VC3D Linux AppImage build after vc_reader started to need concurrentqueue (builder image pin).
- `vc3d-installer-object-convert/`: The VC3D Windows installer ships vc_object_convert next to VC3D.
- `vc-object-convert-in-place/`: vc_object_convert --in-place on Windows: before and after on real VC3D project stores.
- `spiral-find-yx-range/`: extract_surface_tracks.py: the yx range step decodes each chunk row of the predictions once (timings and identical outputs on PHerc0332).
