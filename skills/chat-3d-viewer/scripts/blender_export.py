"""Convert a Blender project or an FBX input in an isolated Blender process."""
from pathlib import Path
import sys

import bpy

source, destination = sys.argv[sys.argv.index('--') + 1:]
options = dict(filepath=destination, export_format='GLB', export_animations=True,
               export_skins=True, export_morph=True)
if Path(source).suffix.lower() == '.blend':
    # Open from the original directory so // textures and linked libraries
    # resolve correctly. Never save, relink or overwrite the source project.
    result = bpy.ops.wm.open_mainfile(filepath=source, load_ui=False, use_scripts=False)
    if 'FINISHED' not in result:
        raise RuntimeError('Could not open Blender project')
    visible = bpy.context.visible_objects
    has_shape_keys = any(getattr(obj.data, 'shape_keys', None) for obj in visible)
    options.update(use_active_scene=True, use_visible=True, export_apply=not has_shape_keys)
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if 'fbx_import' in dir(bpy.ops.wm):
        result = bpy.ops.wm.fbx_import(filepath=source)
    else:
        result = bpy.ops.import_scene.fbx(filepath=source, use_image_search=False)
    if 'FINISHED' not in result:
        raise RuntimeError('FBX import did not finish')
if 'FINISHED' not in bpy.ops.export_scene.gltf(**options):
    raise RuntimeError('Blender could not export GLB')
