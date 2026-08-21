# Pebbleland

`pebbleland_animated.glb` — an animated, procedurally generated landscape: a
dense terrain of rectangular blocks with flat tile plazas and floating glowing
suns, built to match the supplied reference images. Everything ships as **one
self-contained binary GLB**: geometry, materials, lights, cameras and animation
curves all live inside the single file, with no external `.bin`, textures or
side-car assets.

## Files

| File | Purpose |
|---|---|
| `pebbleland_animated.glb` | the artwork — one self-contained binary |
| `pebbleland_animated.metadata.json` | NFT metadata (edit the CID placeholders) |
| `pebbleland_preview.png` | 2000×2000 still for the metadata `image` field |
| `pebbleland_preview_wide.png` | 2000×2000 alternate angle |
| `pebbleland_loop.gif` | 512×512 animated loop, 120 frames @ 12fps |
| `tools/generate_pebbleland.py` | generator + validator |

## How the scene was generated

`tools/generate_pebbleland.py` writes the glTF 2.0 binary directly (Python +
numpy, no Blender in the loop — Blender was not available in this environment).
Regenerate or re-check it with:

```bash
python3 tools/generate_pebbleland.py                    # generate + validate
python3 tools/generate_pebbleland.py --validate-only    # validate only
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
| — of which accent-coloured | 3.3% of scene triangles |
| Animated blocks | **320** (each one costs a draw call, so kept lean for mobile) |
| Suns | **18** (12 low among the blocks, 6 high in the sky) |
| Triangles | 110,750 |
| Draw calls | **426** |
| Nodes / meshes / materials | 465 / 35 / 21 |
| Animation length | **24.0 s**, seamless loop |
| File size | 4.39 MiB |

**Materials** — 8 greys (light grey through near-black) and 6 accents (red,
blue, green, lime/yellow, magenta, cyan), each with its own roughness and a
little metalness on some so surfaces do not read uniformly flat. Accent blocks
are deliberately rare (~4.5% of blocks, 3.3% of scene triangles). Base colours are authored in sRGB
and converted to linear, since glTF `baseColorFactor` is linear.

**Lighting** — 9 warm point lights (`KHR_lights_punctual`), carried by the low
suns, pooling light onto nearby block tops with a bounded range for gentle falloff;
plus three dim cool directional lights (a steep key, a weak side fill and a
rim). The key is deliberately top-down: block tops read bright while sides fall
to near-black, as in the references. Sun cores are emissive with
`KHR_materials_emissive_strength`, so bloom-capable viewers pick them up as HDR
highlights.

**Glow** — each sun is a bright emissive core wrapped in four nested translucent
shells of decreasing alpha. A single shell renders as a hard-edged disc from
every angle (a sphere has the same optical depth at every impact parameter), so
the soft radial falloff has to be built by stacking shells.

**Environment** — a near-black ground plane sits a unit below the block feet, so
every seam reads as black void, and an inward-facing sky dome carries a
vertex-coloured horizon gradient using `KHR_materials_unlit`. Both are sized to
keep the scene's bounding sphere close to the terrain — see Performance.

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
| `Pebbleland_AllMotion` | 338 | everything (suns + blocks) |
| `SunsFloat` | 18 | suns only |
| `BlocksRise` | 320 | blocks only |

The combined clip is **first** because many viewers autoplay only clip 0; the
two isolated clips are there so the suns and the blocks can be driven
separately.

- **Suns** — each sun's X, Y and Z are independent two-frequency sinusoid sums
  with randomised amplitudes, frequencies (1–3 cycles per loop) and phases, so
  no two suns share a speed, direction or phase. Total travel ranges from 1.4 to
  32.9 units per sun, with gentler vertical bobbing than horizontal drift.
- **Blocks** — 320 blocks rise and fall on `y(t) = A/2 · (1 − cos(ωt + φ))`,
  which keeps them within `[0, A]` and never sinks them into the ground.
  Amplitudes span 0.26 to 8.35 units (some barely twitch, some heave several
  storeys), speeds span 1–6 cycles per loop, and phases are fully randomised.
  Only vertical translation is animated — measured horizontal drift is 2.8e-14
  units.

## Performance (built for phones)

The scene is tuned so it runs on a phone, not just a desktop GPU.

**426 draw calls, not 9,000.** The 8,700 static blocks are welded into 14
per-material batched meshes (one mesh per colour, split into primitives of
≤64,000 vertices so 16-bit indices stay valid). Only the 320 animated blocks
remain individual nodes, because in glTF only a node can be animated. Draw
calls break down as 14 batched terrain meshes + 320 animated blocks + 90 sun
primitives + 2 environment.

**110,750 triangles**, down from 153,682, via two cuts that are invisible in
practice:

- every block's bottom face is dropped — the ground sits a unit below and the
  seams are only 0.14 units wide;
- 7,006 side faces fully covered by a taller neighbour are dropped. A face is
  only culled when the neighbour is at least 0.45 units taller *and* is not an
  animated block, so a rising block can never expose a hole.

**Overdraw.** The sun halos are the fill-rate risk on mobile, since they cover
large screen areas. Each shell is single-sided, halving its cost, and the stack
is 4 shells rather than 6.

**9 point lights + 3 directional.** three.js evaluates every punctual light per
fragment in a single pass, so light count is a direct mobile cost. Nine of the
twelve low suns carry a real light; the other three glow without lighting, which
is indistinguishable in practice.

**Bounding volume.** The sky dome (radius 200) and ground plane (420 units) are
sized so the whole scene's bounding sphere is only ~2× the city's. This matters
because NFT and mobile viewers auto-frame the bounding box and *ignore embedded
cameras* — an oversized environment would leave the city as a speck. The dome is
also single-sided with inward winding, so it is invisible from outside while
still providing the dark sky backdrop.

`EXT_mesh_gpu_instancing` would have been smaller and faster still, but was
deliberately *not* used: it would render the file broken in any viewer lacking
the extension, Blender's importer included. Batching gets the same draw-call win
with universal compatibility, at the cost of file size (4.39 MiB rather than
~2 MiB, since merged vertices can no longer be shared).

### Phone viewing caveat

Draw calls, triangles, lights, overdraw and index width were all measured and
are reported by the validator. What could *not* be measured here is real
frame-rate on real handsets — there is no phone in this build environment. The
budgets above (426 draw calls, ~111k triangles, 12 lights) are comfortably
inside what a mid-range 2020-era phone handles at 60 fps, but if you are
targeting very low-end devices, the cheapest further wins are: drop
`TARGET_ANIMATED_BLOCKS` from 320, and reduce `SUN_SHELLS` from 4 entries to 2.

## How to view it

- **Drag and drop** onto <https://gltf-viewer.donmccurdy.com> or
  <https://sandbox.babylonjs.com> — both play animations and honour the embedded
  cameras.
- **`<model-viewer>`**: `<model-viewer src="pebbleland_animated.glb" autoplay
  camera-controls>`.
- **three.js**: `GLTFLoader` → `new THREE.AnimationMixer(gltf.scene)`, then play
  `gltf.animations[0]`. The embedded cameras arrive in `gltf.cameras`.
- **Blender**: File → Import → glTF 2.0. Animation lands on the timeline.

For the closest match to the reference images, select `CineCam_Main` and enable
bloom if your viewer offers it.

**On a phone**, the simplest route is to open the GLB in any mobile browser with
a `<model-viewer>` page, or send it to a phone and open it with the OS 3D viewer
(iOS Quick Look needs USDZ, so on iPhone use a browser-based viewer rather than
the Files app preview).

## Minting it as an NFT

`pebbleland_animated.metadata.json` is a ready-to-use ERC-721 / ERC-1155
metadata document in the schema OpenSea and most marketplaces read. It is
generated by the same script as the GLB, so its traits cannot drift from the
actual scene.

Both URIs in it are **placeholders**:

```json
"image":         "ipfs://REPLACE_WITH_YOUR_CID/pebbleland_preview.png",
"animation_url": "ipfs://REPLACE_WITH_YOUR_CID/pebbleland_animated.glb"
```

To mint:

1. Pin `pebbleland_animated.glb` and `pebbleland_preview.png` to IPFS
   (Pinata, nft.storage, web3.storage, or your own node). Pinning both as one
   directory gives you a single CID for both paths.
2. Replace `REPLACE_WITH_YOUR_CID` in the metadata with that CID.
3. Pin the edited metadata JSON, and use *its* `ipfs://…` URI as the token URI
   in your contract's `tokenURI` / `uri`.

Notes:

- `animation_url` is the field marketplaces use for GLB playback; `image` is the
  static preview used in grids, search results and social embeds, so it should
  stay a plain PNG.
- `background_color` is set to `0B0B10` so marketplaces that honour it frame the
  dark scene on a dark ground.
- Marketplace viewers auto-frame the bounding box and ignore embedded cameras, so
  the default marketplace view is the orbit view, not `CineCam_Main`. The scene
  was sized specifically for this.
- The GLB is self-contained, so the one CID is genuinely all a collector needs —
  nothing is fetched at view time.
- The traits are descriptive of this one artwork. If you mint a collection,
  vary `SEED` in the generator: every seed gives a different terrain, colour
  distribution, skyline and motion, and the metadata regenerates to match.

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
- **Viewers that autoplay only the first clip** will play `Pebbleland_AllMotion`,
  which is why it is ordered first. A viewer that plays *all* clips at once will
  double-apply the sun and block tracks; select a single clip if you see that.

## Still images

The GLB itself has no resolution — it is geometry, not pixels; on-screen
sharpness comes from the viewer's own resolution and anti-aliasing.

`pebbleland_loop.gif` samples the animation at 120 evenly spaced points
across the full 24-second loop. The last frame lands one step *before* t=24 —
whose frame is identical to t=0 — so the GIF loops with no duplicated frame and
no visible seam, exactly as the GLB does. It plays at 12 fps, i.e. about
2.4x real time, so the whole loop reads in a few seconds; the GLB itself is
unaffected and still runs at true speed. A single global palette is generated
across every frame rather than per frame, which keeps colours from shifting
between frames and is what makes a 6.6 MB GIF possible at this size.

The bundled stills are rendered at 3000×3000 with 8× MSAA and a half-float
render target, then LANCZOS-downsampled to 2000×2000. Rendering above the target
size and downsampling is what removes the stair-stepping on block edges; note
that a renderer's `antialias: true` flag does **nothing** when drawing through a
post-processing chain, because that draws into an offscreen render target which
needs its own `samples` setting.

## Validation

`python3 tools/generate_pebbleland.py --validate-only` re-opens the written
file with an independent parser and runs **23 checks**: container integrity,
geometry, materials, accent blocks, suns and lights, animation tracks,
interpolation mode, actual sampled sun motion, actual sampled block motion,
phase desynchronisation, loop closure, self-containment, normals and index
validity, degenerate scales, cameras, and the mobile/NFT budgets — draw calls,
16-bit index range, light count, single-sided translucency, bounding-volume
ratio and sky-dome culling. All 23 pass.

The file was additionally re-parsed with `pygltflib` and rendered in three.js
under headless Chromium — from each embedded camera and from a simulated
marketplace auto-frame orbit — to confirm it loads, animates and looks correct.
