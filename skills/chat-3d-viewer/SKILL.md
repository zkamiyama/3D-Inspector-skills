---
name: chat-3d-viewer
description: Generate a self-contained 3D Inspector for uploaded mesh files (GLB, glTF, OBJ, PLY, STL, 3MF) and Box Impostor .box.zip archives. Prefer native Three.js rendering and three-impostor ray marching for Box assets, with scene statistics, PBR material inspection, RGBA texture channels, UV overlays, OrbitControls, and offline output.
license: MIT
metadata:
  author: Chat 3D Inspector contributors
  version: 0.2.0
---

# Chat 3D Inspector

Create an interactive, portable 3D inspector **from actual supplied model bytes**, not a substitute stock model. The HTML must contain the complete asset payload and pinned Three.js/three-impostor runtime, so it makes **zero network requests when opened**. This is useful in ChatGPT surfaces that prohibit network fetches, and it also works as an ordinary HTML download.

## Inputs and workflow

Supported source types: `.glb`, `.gltf`, `.obj`, `.stl`, `.ply`, `.3mf`, `.box.zip`. For separate `.gltf` binary/textures and OBJ/MTL, keep companion resources next to the source file. Neither 3D Gaussian Splatting nor animation/rigging is supported. If the input is missing, request an upload or use a verified project file; never fabricate asset statistics.

1. Install the Python builder dependencies (`pip install -r requirements.txt`) in an isolated environment. No Node.js is required to build with the committed runtime bundle. The optional NPM build dependencies are used only by **Skill developers** to regenerate the runtime.
2. Generate the output:
   ```sh
   python scripts/build_viewer.py /path/to/model.glb --output /mnt/data/model.inspector.html
   python scripts/build_viewer.py /path/to/asset.box.zip --output /mnt/data/box.inspector.html
   ```
   Native Three.js is the default. Use `--renderer legacy` only for compatibility testing. Choose `--runtime-source cdn` to load pinned Three.js and three-impostor ES modules from jsDelivr while keeping all model bytes inside the HTML. **This mode does not call `fetch()` for model data.** Default `--runtime-source embedded` includes the renderer itself and remains fully offline. Use `--grid 96` to increase the depth-guide mesh used for Canvas2D fallback, **not** native ray-march quality. For large mesh formats, `--max-triangles` limits the displayed faces without altering source files; `--max-texture` limits thumbnail resolution.
3. Read the JSON summary. For an ordinary mesh, `vertices` and `triangles` describe exported preview geometry. `sourceVertices` and `sourceTriangles` describe original geometry before optional reduction. For native Box, the renderer's bounding Box has **24 vertices and 12 triangles**, while `sourceVertices/SourceTriangles` describe the embedded proxy and `fallbackVertices/fallbackTriangles` describe the sampled surface mesh. These counts must **never** be conflated.
4. Test loading, 3D orbit, camera presets, visibility toggles, Materials and Textures tabs, channel controls, and UV overlay. Test both Three.js WebGL2 and intentional Canvas2D fallback when possible. If a tool is available for running a browser, capture an actual screenshot and report whether requests reached any external URLs.
5. When ChatGPT supports inline interactive HTML, embed the **complete HTML and payload**, not an iframe pointed at a local filesystem path. If embedding is unsupported or too large, provide a verified download link and screenshot. Do not claim all ChatGPT clients support WebGL2.

## Rendering behavior

- **Box Impostor `.box.zip`:** Default uses pinned Three.js `WebGPURenderer({forceWebGL:true})` plus upstream `three-impostor/ImpostorNodeMaterial`, loading the **original lossless RGBA16F** color, normal, interval, range and material data with the factory's WebGL row-orientation and filtering semantics. Six depth guides are **not** used for the native raymarch; they only generate the fallback triangle surface. The built-in inspector has texture preview, color channel controls and original-proxy counts. Wire shows the bounding box; the native surface normals mode is disabled rather than pretending a sampled mesh normal is the raymarched hit normal.
- **GLB/glTF/OBJ/PLY/STL/3MF:** Extract triangle meshes, material factors and texture assets via trimesh, then render via official Three.js `MeshStandardMaterial` and `OrbitControls` (rather than a custom PBR fragment shader). Supports base color texture, vertex colors, normal map, roughness and metalness maps, emissive and some AO data where provided by conversion. It does **not** guarantee full glTF extension semantics: clearcoat, transmission, variants, skinning, animation, tangent features and color-management edge cases remain limited.
- **Canvas2D fallback:** When WebGL2 is unavailable, use the simplified triangle renderer. The native Box therefore becomes a **surface reconstruction** and may look faceted. Clearly disclose this downgrade. The Canvas2D fallback does not sample every material texture at each pixel.
- **Runtime choices:** `embedded` (default) embeds both libraries and model data; display uses no network. `cdn` embeds all model data but imports pinned Three.js and three-impostor modules from jsDelivr. In the user's sidebar test, CDN `fetch()` failed while dynamic ESM imports and WebGL2 succeeded. Native rendering with `window.fetch` forcibly rejected also succeeded in an Edge sandboxed HTML test. **Different ChatGPT clients may enforce different CSP rules.** On CDN failure, the viewer falls back to Canvas2D. Do not claim all clients behave alike.

## UI and safety

Keep the model visual dominant. **Do not add a separate app header or footer.** Place camera presets, view controls, screenshot and help in a compact floating toolbar **inside the top-left corner of the 3D canvas**. Keep the model title as a small lower-left overlay. The right inspector uses narrow tabs, low-padding statistics and tight property rows. On mobile, wrap the toolbar inside the viewport and stack the inspector below it. Reuse the provided neutral graphite UI and Details / Materials / Textures inspector tabs. Show mesh/material visibility, dimensions, original and rendered counts, UV overlays and RGBA/R/G/B/A channels. The visual system was informed by [unslop](https://github.com/heydamir/unslop), Damir Sokolovsky (CC BY 4.0); do not import its assets or claim authorship of the original skill.

Validate archive member paths, map/depth/guide checksums (when present), size limits and no unsafe extraction before embedding. Never fetch arbitrary remote assets from the viewer itself. Asset data is embedded in the generated HTML, so do not share private models without permission. The runtime bundle contains Three.js and three-impostor under their MIT licenses; copy the notices in `assets/THIRD_PARTY_LICENSES.txt` into generated HTML.

## Reporting

Lead with the **actual** interactive 3D asset when supported, otherwise an actual render screenshot and link. Include source format, native/Canvas2D mode, measured counts, material/texture summaries, rendering limitations, and evidence of any offline/CSP checks. For Box assets, distinguish native raymarching from fallback triangulation. The Skill is installable source; publishing it does not enable it automatically for all ChatGPT accounts.
