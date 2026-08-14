# digital_city_animated.glb

An animated, procedurally generated "digital landscape" — a dense terrain of
rectangular blocks with flat tile plazas and floating glowing suns — built to
match the supplied reference images. Everything ships as **one self-contained
binary GLB**: geometry, materials, lights, cameras and animation curves all live
inside the single file, with no external `.bin`, textures or side-car assets.

## How the scene was generated

`tools/generate_digital_city.py` writes the glTF 2.0 binary directly (Python +
numpy, no Blender in the loop — Blender was not available in this environment).
Regenerate or re-check it with:

```bash
python3 tools/generate_digital_city.py                    # generate + validate
python3 tools/generate_digital_city.py --validate-only    # validate only
```

Output is deterministic: seed `20260814` always produces the identical file.

The terrain comes from a layered value-noise fBm height field on a 108 × 108
cell grid (2.0 units per cell, 216 × 216 units overall):

- **Large-scale terrain** — two fBm octave stacks plus a ridged layer set the
  overall rise and fall of the landscape.
- **Tower clusters** — nine gaussian bumps, modulated by a high-frequency noise
  so they break into individual towers rather than smooth hills, form the distant
  skyline.
- **Per-cell jitter** — a random 0–2.1 unit offset, quantised to 0.5 unit steps,
  gives the stepped cube-mosaic look of the close-up references.
- **Plazas** — a separate noise field, plus two authored bands, flattens whole
  regions into thin floor tiles with wide black seams.
- **Spikes** — ~1.6% of cells get an extra 3–14 units, biased toward accent
  colours; these are the tall thin coloured towers in the references.
- **Footprints** — neighbouring cells merge into 2×1 and 2×2 blocks (more often
  for tall ones), so widths and depths vary rather than every block being 1×1.
- Camera sight-lines get corridor masks, so each camera reliably faces the
  subject it was framed for, and a clearance disc under each viewpoint keeps
  spikes from impaling the camera.

## Contents

| | |
|---|---|
| Blocks | **9,020** (4,563 raised blocks + 4,457 flat plaza tiles) |
| — of which multi-cell footprints | 1,078 |
| — of which accent-coloured | 410 |
| Animated blocks | **850** (9% of the block field) |
| Suns | **18** (12 low among the blocks, 6 high in the sky) |
| Triangles | 153,682 |
| Nodes / meshes / materials | 9,190 / 23 / 23 |
| Animation length | **24.0 s**, seamless loop |
| File size | 1.95 MiB |

**Materials** — 8 greys (light grey through near-black) and 6 accents (red,
blue, green, lime/yellow, magenta, cyan), each with its own roughness and a
little metalness on some so surfaces do not read uniformly flat. Accent blocks
are deliberately rare (~4.5% of the field). Base colours are authored in sRGB
and converted to linear, since glTF `baseColorFactor` is linear.

**Lighting** — 12 warm point lights (`KHR_lights_punctual`), one per low sun,
pooling light onto nearby block tops with a bounded range for gentle falloff;
plus three dim cool directional lights (a steep key, a weak side fill and a
rim). The key is deliberately top-down: block tops read bright while sides fall
to near-black, as in the references. Sun cores are emissive with
`KHR_materials_emissive_strength`, so bloom-capable viewers pick them up as HDR
highlights.

**Glow** — each sun is a bright emissive core wrapped in six nested translucent
shells of decreasing alpha. A single shell renders as a hard-edged disc from
every angle (a sphere has the same optical depth at every impact parameter), so
the soft radial falloff has to be built by stacking shells.

**Environment** — a large near-black ground plane sits a unit below the block
feet, so every seam reads as black void, and an inward-facing sky dome carries a
vertex-coloured horizon gradient using `KHR_materials_unlit`.

**Cameras** — three, in this order:

1. `CineCam_Main` — elevated, wide (62° vertical), looking across the dense
   block field toward the tallest cluster (references 1 & 2).
2. `CineCam_Plaza` — sweeping the flat tile plaza (reference 3).
3. `CineCam_Wide` — high and distant over the whole landscape (reference 4).

Aspect ratio is intentionally left unset so each camera adapts to the viewer's
viewport instead of letterboxing.

## Animation

All motion is baked as glTF `CUBICSPLINE` keyframes with analytic tangents.
Every component is a sum of sinusoids whose periods divide the 24 s loop
exactly, so the first and last keyframe agree in both value *and* derivative —
the loop closes with zero discontinuity (measured `max |p(0) − p(T)| = 0.0`).

Three animation clips are present:

| Clip | Channels | What moves |
|---|---|---|
| `DigitalCity_AllMotion` | 868 | everything (suns + blocks) |
| `SunsFloat` | 18 | suns only |
| `BlocksRise` | 850 | blocks only |

The combined clip is **first** because many viewers autoplay only clip 0; the
two isolated clips are there so the suns and the blocks can be driven
separately.

- **Suns** — each sun's X, Y and Z are independent two-frequency sinusoid sums
  with randomised amplitudes, frequencies (1–3 cycles per loop) and phases, so
  no two suns share a speed, direction or phase. Total travel ranges from 1.4 to
  32.9 units per sun, with gentler vertical bobbing than horizontal drift.
- **Blocks** — 850 blocks rise and fall on `y(t) = A/2 · (1 − cos(ωt + φ))`,
  which keeps them within `[0, A]` and never sinks them into the ground.
  Amplitudes span 0.26 to 8.47 units (some barely twitch, some heave several
  storeys), speeds span 1–6 cycles per loop, and phases are fully randomised.
  Only vertical translation is animated — measured horizontal drift is 2.8e-14
  units.

## Performance

The block field is **instanced, not duplicated**: 9,148 mesh nodes share just
**4 unique geometries** (a 24-vertex unit cube, an icosphere, a ground quad and
the sky dome) — a 2,287× reuse factor. Per-block variation is entirely node
TRS, and each material gets its own lightweight mesh pointing at the *same*
vertex accessors. That is why 9,000+ blocks fit in under 2 MiB.

The trade-off: node-level instancing is what plain glTF 2.0 offers, so a viewer
will issue roughly one draw call per block. That is comfortable on desktop but
can be heavy on low-end mobile. If you need fewer draw calls, either merge the
static blocks per material at load time, or have a runtime batch them into an
InstancedMesh — the shared-geometry layout makes both trivial. `EXT_mesh_gpu_instancing`
was deliberately *not* used, because it would render the file broken in viewers
that lack the extension (Blender's importer among them).

## How to view it

- **Drag and drop** onto <https://gltf-viewer.donmccurdy.com> or
  <https://sandbox.babylonjs.com> — both play animations and honour the embedded
  cameras.
- **`<model-viewer>`**: `<model-viewer src="digital_city_animated.glb" autoplay
  camera-controls>`.
- **three.js**: `GLTFLoader` → `new THREE.AnimationMixer(gltf.scene)`, then play
  `gltf.animations[0]`. The embedded cameras arrive in `gltf.cameras`.
- **Blender**: File → Import → glTF 2.0. Animation lands on the timeline.

For the closest match to the reference images, select `CineCam_Main` and enable
bloom if your viewer offers it.

## Limitations of GLB animation and runtime behaviour

- **GLB cannot carry post-processing.** Bloom, glare, tone mapping and
  anti-aliasing are viewer-side settings. The emissive cores and nested glow
  shells approximate bloom geometrically so the suns still read as glowing
  without any post-fx, but a viewer with real bloom will look markedly closer to
  the references. Screenshots here used ACES tone mapping with a light bloom.
- **glTF has no ambient light term and no fog.** The dark ambience is carried by
  three dim directional lights and a dark sky dome. Atmospheric depth is
  therefore approximate.
- **Shadows are not part of glTF.** Nothing in the file casts shadows; whether
  shadows appear is entirely up to the viewer. The scene is lit so it reads
  correctly without them.
- **Punctual lights are widely but not universally supported.** Viewers that
  ignore `KHR_lights_punctual` and light purely from an environment map will
  render a flatter, brighter scene; emissive suns and base colours still show.
  Conversely, a viewer that adds a bright default IBL *on top* of the 15 embedded
  lights may look over-exposed — lower the exposure if so.
- **Animation cannot branch or respond to input.** It is a fixed 24 s loop; the
  organic, unsynchronised feel comes from baked incommensurate frequencies, not
  from runtime logic.
- **`CUBICSPLINE` triples the keyframe data** versus linear, which is the cost of
  genuinely smooth interpolation from few keys. It is well supported (three.js,
  Babylon, model-viewer, Blender), but a minimal hand-rolled loader that only
  implements `LINEAR` will not play these curves correctly.
- **Viewers that autoplay only the first clip** will play `DigitalCity_AllMotion`,
  which is why it is ordered first. A viewer that plays *all* clips at once will
  double-apply the sun and block tracks; select a single clip if you see that.

## Validation

`python3 tools/generate_digital_city.py --validate-only` re-opens the written
file with an independent parser and runs 18 checks — container integrity,
geometry, materials, accent blocks, suns and lights, animation tracks,
interpolation mode, actual sampled sun motion, actual sampled block motion,
phase desynchronisation, loop closure, self-containment, normals and index
validity, degenerate scales, instancing, and cameras. All 18 pass. The file was
additionally re-parsed with `pygltflib` and rendered in three.js
(headless Chromium) to confirm it loads, animates and looks correct.
