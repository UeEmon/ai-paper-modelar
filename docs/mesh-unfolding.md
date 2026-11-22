# OBJ/STL 3D mesh unfolding

## UI workflow

1. In `05 / 3D MESH UNFOLDING`, upload one `.obj` or `.stl` file. Textures/MTL are not imported.
2. Set the coordinate unit used at export (`mm`, `cm`, or `m`), then the model scale (`1/X`). STL does not declare a standard unit.
3. Optionally disable glue tabs. Run the unfolding operation.
4. Inspect the reported vertex/triangle counts, sheet count, approximate 3D bounds, open-edge warnings and number of net islands.
5. Navigate SVG page previews and save individual SVG pages or one multipage A4 vector PDF. Print at **100%**, measure the 50 mm calibration mark, and test-assemble before using expensive material.
6. When a project is selected, tick **Save original OBJ/STL to this project** to persist the original file. Reopen it later via the reference library's **Unfold this 3D model** button; the temporary sheet generation is repeated as needed.

## Supported source data

- OBJ: `v` vertices and `f` faces, including negative relative indices and standard `v/vt/vn` face tokens. A polygon with more than three vertices uses triangle-fan subdivision, so pre-triangulate nonconvex or nonplanar faces in Blender/CAD first.
- STL: binary triangle records and UTF-8 ASCII `vertex` sections. Triangle vertices are welded by 7-decimal-place coordinate quantization to recover shared edges.
- Limits: file <= 5 MiB, <= 20,000 vertices, <= 500 triangle faces, <= 100 printable A4 pages, <= 8 in-memory jobs with one-hour expiry. More detailed meshes must be simplified before import.
- Model dimensions are converted to physical millimetres by multiplying the chosen source-unit conversion factor and dividing by the scale denominator.

## Unfolding algorithm

1. Reject invalid triangle indices, non-finite coordinates, zero-area faces and edges shared by 3 or more triangles.
2. Build undirected edge-to-triangle adjacency; count boundary edges and flag open meshes.
3. Flatten a root triangle using its three Euclidean edge lengths.
4. For each adjacent triangle, keep shared 2D edge positions unchanged and locate the third vertex by distance preservation, on the opposite side of the parent triangle.
5. Use convex polygon clipping to reject candidates whose interior would overlap a face already in that connected net island. Rejected candidates are tried from other parents, then split into further islands when necessary.
6. Shared edges selected as connected hinges become dashed fold lines. Cut edges become solid cutting strokes. Where feasible, simple tapered tabs are placed on selected cut seams.
7. Turn each island into a vector part with a 6 mm bounding margin; use the existing shelf-packing/tile layout for A4 pages. The same placement coordinates drive SVG and PDF.

## API

POST `/api/mesh/jobs` with multipart fields `file`, `source_unit`, `scale`, `glue_tabs`.

Example:

```sh
curl -F 'file=@model.stl' -F 'source_unit=mm' -F 'scale=12' -F 'glue_tabs=true' \
  http://localhost:8086/api/mesh/jobs
```

The response includes `id`, `pages`, `stats`, `warnings` and an expiry time. Subsequent endpoints:

- `GET /api/mesh/jobs/{id}`
- `GET /api/mesh/jobs/{id}/pages/{page}.svg` (zero-indexed page)
- `GET /api/mesh/jobs/{id}/template.pdf`
- `DELETE /api/mesh/jobs/{id}`

The raw original 3D model is **not retained** in the in-memory job. Projects can store `.obj` and `.stl` originals in the local Docker volume; stored models are excluded from AI image reference uploads.

## Important limitations

- This is a bounded **triangular-surface net prototype**, not an industrial geometric unfolding or mesh repair system. It does not globally optimize the number of islands, material use or assembly sequence.
- Shared boundaries can be nonmanifold or poorly oriented even when every edge has <= 2 incident faces. The implementation does not prove globally consistent manifold topology, watertightness or absence of 3D self-intersections.
- Net tabs and cut lines do not account for paper thickness, kerf, fold allowances, edge labeling or physical material strength. Some seams may need manually designed tabs.
- No texture UV transfer, vertex normal shading, 3D interactive viewer, CAD exports, mountain/valley fold distinction, automatic mesh simplification or polygon tessellation of nondevelopable curves.
- Never process unknown sources in a publicly exposed multiuser deployment without authentication, task isolation, strict resource limits, anti-malware inspection and rate limiting. The default Docker deployment binds the port to localhost.

## Tests

`tests/test_mesh_unfolder.py` checks OBJ/STL parsers, 3D topological validation, non-overlapping unfolding, page-rendered SVG/PDF, API validations and cleanup.
`tests/test_mesh_projects.py` checks persistence of mesh originals, preview rendering, project copying, and exclusion from AI image input.
