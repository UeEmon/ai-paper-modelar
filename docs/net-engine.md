# Parametric paper net engine

## Geometry and units

All input sizes are real-world metres. The drawing engine computes millimetres using `mm = real_m × 1000 / scale` and emits vector SVG/PDF at exact A4 physical size. The field `input_unit` is only a Web UI display preference; API model measurements remain metres.

| Template | Main geometry | Parts |
|---|---|---|
| `building` | existing orthogonal walls and gable/flat roof | 4 walls + 1–2 roofs |
| `box` | legacy independent cuboid faces | 6 separate faces |
| `cylinder` | developed rectangular shell, circumference `π×D` | one scored shell, two circular caps |
| `cone` | annular sector or full radial sector | developed shell, bottom cap and optional top cap |
| `prism` | regular n-gon side strip, side `D sin(π/n)` | one scored strip + two polygon caps |
| `pyramid` | regular n-gon with n triangular side faces | base + n triangles |

For a regular polygon, `width_m` is the diameter of its circumscribing circle. For cylinder/cone, it is the outer bottom diameter. For these four shapes `depth_m` is not used and the summary reports the effective depth equal to the diameter. `height_m` is the vertical height. The sides field allows integers from 3 to 12.

### Conical frustum formula

Let bottom radius be `r0`, upper radius be `r1`, and vertical height be `h`. For `0 ≤ r1 < r0`, the slant width `s = sqrt(h² + (r0-r1)²)`; the developed outer radius `R = s*r0/(r0-r1)` and inner radius `Rinner = s*r1/(r0-r1)`. The sector angle is `θ = 2π*r0/R` radians. The outer and inner arc lengths are therefore `2πr0` and `2πr1`. For `r1=0`, the inner arc collapses to the cone apex; for `r1=r0`, the geometry becomes a cylinder. Curves are sampled to short chords; they are an approximation suitable for printing, not a continuous mathematical SVG arc.

### Polygonal prism and pyramid

For n equal sides and circumradius r, edge length is `2*r*sin(π/n)` and apothem is `r*cos(π/n)`. The prism unrolls to n adjacent rectangles joined along scored vertical edges. The pyramid triangular side face has a base equal to the polygon side and face altitude `sqrt(h²+apothem²)`.

## Geometry pipeline

1. Pydantic validates scale, dimensions, template, ratio and polygon edge count.
2. Template-specific pure geometry creates cut outline polygons and separate score/fold line primitives.
3. A part bounding-box pass normalizes all coordinates to positive millimetres with a six millimetre margin.
4. `page_jobs` uses a rectangular shelf-packing algorithm for small independent parts. Large parts are tiled with 5 mm overlap. It checks the required tile count *before* creating page descriptors; >100 pages is rejected.
5. ReportLab and SVG renderers consume the exact same page-placement descriptors and crop windows; multiple parts can share one A4 page without overlapping.
6. Each SVG graphic includes a `data-layer` tag (`cut`, `fold`, or `detail`) for post-processing. The 50 mm reference stroke on each A4 page must be checked with a ruler after printing at 100% (never print 'fit to page').

## Paper assembly conventions

- Outer solid contours are cut; dashed lines are scored/folded.
- The polygon/cylinder side is unrolled as one continuous strip with a side seam tab and a series of small cap-attachment tabs.
- The cone side uses a seam tab. Its end caps and pyramid base have perimeter tabs to attach the side material.
- The pyramid has separate triangles with one side seam tab each.
- Small finished parts are packed efficiently, but the engine does not unfold arbitrary polyhedral meshes into one overlap-free connected net. Large parts are tiled across pages.
- Printing can distort scale. Material thickness, kerf, grain direction, folded-edge correction, and mechanical stability are not compensated. Always prototype first.

## Compatibility

The defaults (`template='building'`, 1/150 scale where specified) remain backwards compatible with saved projects and SenroLab's existing `/v1/nets` endpoint. SenroLab's own page-packing API remains separate and unchanged by the new template logic.

## Verification

`tests/test_net_engine.py` verifies basic template PDF/SVG generation, geometric perimeter and arc lengths, polygon face counts, cut/fold line classification, coordinate bounding, validation and fast rejection of overly large projects. The GitHub Actions CI runs Python tests and JavaScript syntax checks.

## Not yet implemented

Arbitrary OBJ/STL/glTF mesh import and graph-based unfolding, curved surfaces with non-developable Gaussian curvature, interlocking tab optimization, paper-thickness offsets, 3D preview, digital cutting file formats and validated manufacturing tolerances.
