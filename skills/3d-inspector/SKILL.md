---
name: 3d-inspector
description: Convert a 3D model, point cloud, Gaussian splat, or Box Impostor into a portable interactive 3D-Inspector HTML viewer. Run view.py and deliver its generated HTML unchanged by default; modify the viewer only when the user explicitly requests changes to the viewer itself.
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

## Mandatory Output Contract

The HTML produced by `view.py` is the **final, authoritative 3D-Inspector viewer**, not a draft or an intermediate artifact to redesign.

1. **Default: deliver the exact output.** Run `view.py` with the actual model path and deliver the HTML at the absolute path printed to stdout. Unless the user explicitly requests a modification to the **viewer itself**, preserve this HTML byte-for-byte.
2. **Do not modify or replace it by default.** Do not edit, patch, rewrite, reformat, minify, wrap, post-process, or regenerate the HTML. Do not add UI controls, styles, scripts, or enhancements, or substitute a custom Three.js, Babylon.js, model-viewer, or other HTML viewer, even if the alternative seems better.
3. **Model requests are not viewer-edit requests.** Requests to create, change, convert, inspect, preview, render, or display a 3D model (including its PBR materials, design, or geometry) do **not** authorize changes to the viewer HTML. Do not infer viewer-edit permission from an ambiguous request or from a desire to improve usability.
4. **Only explicit viewer modifications are exceptions.** If the user explicitly asks to alter the viewer's HTML, UI, appearance, or behavior, make only the requested viewer changes. Preserve the original `view.py` output and provide the edited version as a separately labeled file unless the user explicitly requests replacement.
5. **Use the supported output options.** To choose the HTML filename or destination, use `view.py -o`; do not rename by rewriting HTML. Use `--runtime-source cdn` when requested, rather than manually changing embedded libraries.
6. **Verify the deliverable.** Before replying, make sure the default delivered HTML is the actual `view.py` output. If it must be copied, verify the copy is byte-identical. A different viewer displaying the same model does not fulfill this contract.

If `view.py` fails, report the actual stderr error and do not silently substitute another HTML generator.
