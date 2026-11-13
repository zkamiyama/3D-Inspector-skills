---
name: chat-3d-viewer
description: Turn an uploaded 3D model or Box Impostor archive into an interactive, portable HTML preview for ChatGPT or a browser. Use for mesh, material, point cloud, Gaussian splat and animated glTF inspection.
license: MIT
metadata:
  version: 0.3.0
---

# Chat 3D Inspector

Run this from the skill directory, substituting the path to the supplied model. From another directory use the absolute path to `view.py`.

```sh
python view.py "/path/to/model.glb"
```

Return the HTML at the absolute path printed on stdout as a clickable file. Use the original model and keep its local companion files alongside it. The command selects the importer, installs missing Python conversion dependencies in a private cache, and embeds the runtime and model into one offline HTML. The browser selects WebGPU, WebGL2 or the limited Canvas 2D view when opened.

Use `-o /path/to/preview.html` for a requested output location. If a small network-loaded sidebar preview is requested, add `--runtime-source cdn`. Model bytes stay embedded. On failure, give the specific input or dependency error printed on stderr. See [supported formats and limits](README.md) only when needed.
