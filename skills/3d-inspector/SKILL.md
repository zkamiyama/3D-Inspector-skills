---
name: 3d-inspector
description: Convert an uploaded 3D model, point cloud, Gaussian splat, or Box Impostor into a portable interactive 3D-Inspector HTML viewer.
license: MIT
metadata:
  version: 0.3.1
---

# 3D-Inspector

Pass the **actual model path** to the launcher and deliver the generated HTML. The command chooses the importer and rendering modules, prepares any missing Python dependencies in its own cache, and prints exactly one absolute HTML path.

```sh
python view.py "/path/to/model.glb"
```

Run from this Skill directory, or call `view.py` with its absolute path. Preserve companion files such as glTF `.bin` and OBJ textures alongside the input. Return the printed HTML file to the user; do not replace it with an unrelated image.

Optional: `-o /path/to/output.html` chooses the destination. `--runtime-source cdn` makes a smaller HTML that imports pinned rendering libraries but embeds the model. Default output is self-contained and offline. WebGPU is chosen automatically when supported, with WebGL2/Canvas 2D fallbacks.

If conversion fails, report the actual stderr error. Do not perform speculative conversion steps before trying `view.py`. Refer to the repository README only when format limitations matter.
