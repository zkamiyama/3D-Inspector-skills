# Chat 3D Inspector

Run `python view.py /path/to/model.glb` from this directory. The last line on stdout is the absolute path to the HTML. By default, `scene.glb` produces `scene.glb.inspector.html` in the current directory. Use `-o preview.html` to choose the name. The installed skill includes its compiled renderers. Node.js is used when decoding required meshopt geometry or KTX2/Basis textures and when rebuilding the renderers from source.

Compressed glTF with Draco triangles or KHR/EXT meshopt is decoded at export. Meshopt and KTX2/Basis use local Node.js when the file has no usable fallback. KTX2/Basis textures become PNG in the HTML. DracoPy, OpenUSD and Open CASCADE are conversion-only Python dependencies installed on demand.

The default HTML contains the renderer, model and textures. `--runtime-source cdn` keeps the model embedded and imports pinned ES modules from jsDelivr. WebGPU is selected when initialization and first-frame validation succeed. WebGL2 and then a limited Canvas 2D view cover other environments. The lower-left indicator names the active backend.

| Input | Display |
| --- | --- |
| GLB, glTF | Static meshes use a compact PBR path. Skins, morph targets, clips and supported glTF material extensions select GLTFLoader. Local `.bin` and image resources are resolved during conversion. |
| OBJ/MTL, STL, OFF, 3MF, DAE | Static triangle meshes with available colors, materials and textures. Keep local sidecar files alongside the model. |
| FBX, BLEND | Blender on PATH converts the asset to GLB. BLEND includes visible objects in the active scene and glTF-exportable materials and animation. |
| STEP/STP, IGES/IGS, BREP | Open CASCADE tessellates solids and trimmed faces into a static mesh. CAD dimensions, drafting annotations and assembly colors are not imported. |
| USD, USDA, USDC, USDZ | OpenUSD evaluates the stage at its start time, including transforms, metric scale and supported Preview Surface inputs. |
| PLY, XYZ | Triangle meshes or point sets. XYZ accepts positions with optional RGB or RGBA. |
| Gaussian PLY, SPLAT | Gaussian primitives with their opacity, shape and orientation. The Canvas fallback draws centers. |
| `.box.zip` | Native `three-impostor` ray marching with the original RGBA16F maps. The bounding box has 24 vertices and 12 triangles. Canvas fallback uses sampled surfaces. |

The orientation gizmo snaps to each signed axis, including the bottom view. Drag the gizmo or model to orbit. Click the front-most axis twice to see its opposite. `P` switches between perspective and orthographic projection. `F` frames the model while retaining its direction. **Details** opens the inspector for statistics, mesh visibility, material isolation, texture channels and UVs. Animation controls appear for clips only.

`view.py` uses a suitable existing Python environment or prepares a cached one. The first install needs access to Python packages. For offline conversion, preinstall `requirements.txt` and the optional input-specific dependencies. `scripts/build_viewer.py` exposes the same conversion flags and emits JSON with original and preview counts. Use `--max-triangles`, `--max-points` and `--max-texture` to limit converted previews. An original animated glTF scene retains its geometry; the triangle cap applies to its static fallback. `--grid` adjusts the Box fallback.

Embedded Box rendering uses Three.js 0.186.0 and three-impostor 0.4.1. Third-party license notices are included in generated HTML. The HUD's original graphite styling drew on Damir Sokolovsky's unslop (CC BY 4.0).
