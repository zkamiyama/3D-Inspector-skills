import base64
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_viewer import build

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def decode_scene(page):
    payload = re.search(r'<script id="scene-payload"[^>]*>([^<]+)', page.read_text()).group(1)
    return json.loads(zlib.decompress(base64.b64decode(payload)))


class FormatTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.page = self.directory / 'view.html'

    def test_real_mesh_round_trip(self):
        cube = trimesh.creation.box(extents=[4, 2, 1])
        for ext in ('off', '3mf', 'dae'):
            with self.subTest(extension=ext):
                path = self.directory / ('part.' + ext)
                cube.export(path)
                stats = build(path, self.page)
                self.assertEqual(stats['runtimeProfile'], 'mesh')
                self.assertEqual(stats['triangles'], 12)
                scene = decode_scene(self.page)
                np.testing.assert_allclose(scene['bounds']['min'], [-2, -1, -.5])
                np.testing.assert_allclose(scene['bounds']['max'], [2, 1, .5])
                self.assertNotIn('uv', scene['meshes'][0])
                self.assertNotIn('fallbackColors', scene['meshes'][0])

    @unittest.skipUnless(shutil.which('blender'), 'optional FBX converter is unavailable')
    def test_binary_fbx_conversion_with_blender(self):
        fbx = self.directory / 'from Blender.fbx'
        # Export Blender's factory cube by itself as an actual binary FBX.
        source = ("import bpy,sys; "
                  "bpy.ops.export_scene.fbx(filepath=sys.argv[-1], object_types={'MESH'})")
        subprocess.run(['blender', '--background', '--factory-startup', '--disable-autoexec',
                        '--threads', '1', '--python-exit-code', '1', '--python-expr', source,
                        '--', str(fbx)], check=True, capture_output=True)
        stats = build(fbx, self.page)
        self.assertEqual(stats['triangles'], 12)
        self.assertEqual(stats['runtimeProfile'], 'mesh')
        self.assertEqual(decode_scene(self.page)['format'], 'FBX')

    @unittest.skipUnless(shutil.which('blender'), 'optional Blender converter is unavailable')
    def test_blend_preserves_texture_animation_modifier_and_source(self):
        from PIL import Image
        src = self.directory / 'animated.blend'
        image = self.directory / 'look.png'
        Image.new('RGB', (8, 4), (20, 111, 167)).save(image)
        setup = self.directory / 'fixture.py'
        setup.write_text("""import bpy, sys
from pathlib import Path
out = Path(sys.argv[-1])
obj = bpy.data.objects['Cube']
mat = bpy.data.materials.new('Albedo')
mat.use_nodes = True
tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
tex.image = bpy.data.images.load(str(out.parent / 'look.png'))
tex.image.filepath = '//look.png'
mat.node_tree.links.new(tex.outputs['Color'], mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
obj.data.materials.clear()
obj.data.materials.append(mat)
obj.modifiers.new('Edges', 'BEVEL').width = .15
obj.keyframe_insert('location', frame=1)
obj.location.x = 2
obj.keyframe_insert('location', frame=18)
bpy.context.scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(out), relative_remap=False)
""")
        subprocess.run(['blender', '--background', '--factory-startup', '--disable-autoexec',
                        '--threads', '1', '--python-exit-code', '1', '--python', str(setup),
                        '--', str(src)], check=True, capture_output=True)
        before = (src.read_bytes(), image.read_bytes())
        stats = build(src, self.page)
        self.assertEqual(stats['runtimeProfile'], 'gltf')
        self.assertGreater(stats['triangles'], 12)
        self.assertEqual(stats['textures'], 1)
        self.assertEqual(decode_scene(self.page)['format'], 'BLEND')
        self.assertEqual(before, (src.read_bytes(), image.read_bytes()))

    def test_openusd_encodings_and_transformed_meshes(self):
        try:
            from pxr import Sdf, Usd, UsdGeom, UsdShade, UsdUtils
        except ImportError:
            self.skipTest('optional OpenUSD dependency not installed')
        from PIL import Image
        src = self.directory / 'stage.usda'
        stage = Usd.Stage.CreateNew(str(src))
        UsdGeom.SetStageMetersPerUnit(stage, 1)
        UsdGeom.SetStageUpAxis(stage, 'Z')
        root = UsdGeom.Xform.Define(stage, '/World')
        stage.SetDefaultPrim(root.GetPrim())
        cube = UsdGeom.Cube.Define(stage, '/World/Cube')
        cube.CreateSizeAttr(2)
        cube.AddTranslateOp().Set((4, 5, 6))
        mesh = UsdGeom.Mesh.Define(stage, '/World/Concave')
        mesh.CreatePointsAttr([(0,0,0), (2,0,0), (2,2,0), (1,1,0), (0,2,0)])
        mesh.CreateFaceVertexCountsAttr([5])
        mesh.CreateFaceVertexIndicesAttr([0,1,2,3,4])
        st = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.TexCoord2fArray,
                                                    UsdGeom.Tokens.faceVarying)
        st.Set([(0,0), (1,0), (1,1), (.5,.5), (0,1)])
        Image.new('RGB', (4, 2), 'magenta').save(self.directory / 'asset.png')
        mat = UsdShade.Material.Define(stage, '/World/Mat')
        shader = UsdShade.Shader.Define(stage, '/World/Mat/PBR')
        shader.CreateIdAttr('UsdPreviewSurface')
        texture = UsdShade.Shader.Define(stage, '/World/Mat/Albedo')
        texture.CreateIdAttr('UsdUVTexture')
        texture.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath('asset.png'))
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(), 'rgb')
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)
        stage.GetRootLayer().Save()
        for ext in ('.usd', '.usdc'):
            stage.GetRootLayer().Export(str(src.with_suffix(ext)))
        self.assertTrue(UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(str(src)), str(src.with_suffix('.usdz'))))
        for ext in ('.usd', '.usda', '.usdc', '.usdz'):
            with self.subTest(extension=ext):
                stats = build(src.with_suffix(ext), self.page)
                self.assertEqual((stats['vertices'], stats['triangles'], stats['meshes']), (13, 15, 2))
                self.assertEqual(stats['textures'], 1)
                scene = decode_scene(self.page)
                self.assertEqual(scene['unit'], 'meters')
                np.testing.assert_allclose(scene['bounds']['max'], [5, 7, 0], atol=1e-6)
                np.testing.assert_allclose(scene['bounds']['min'], [0, 0, -6], atol=1e-6)

    def test_ply_xyz_points_retain_colors_without_triangles(self):
        points = np.array([[0, 0, 0], [0, 1, 0], [2, 0, 0]])
        colors = np.array([[0, 1, 255, 255], [0, 255, 2, 255], [255, 0, 2, 255]], dtype=np.uint8)
        xyz = self.directory / 'scan.xyz'
        np.savetxt(xyz, np.column_stack((points, colors)))
        ply = self.directory / 'scan.ply'
        trimesh.points.PointCloud(points, colors).export(ply)
        for path in (xyz, ply):
            with self.subTest(extension=path.suffix):
                stats = build(path, self.page, max_points=2)
                self.assertEqual((stats['vertices'], stats['sourceVertices'], stats['triangles']), (2, 3, 0))
                scene = decode_scene(self.page)
                cloud = scene['meshes'][0]
                self.assertEqual(scene['previewType'], 'points')
                self.assertEqual(cloud['primitive'], 'points')
                self.assertNotIn('indices', cloud)
                rgba = np.frombuffer(base64.b64decode(cloud['colors']), dtype=np.uint8).reshape(-1, 4)
                np.testing.assert_array_equal(rgba, colors[[0, 2]])
                np.testing.assert_allclose(scene['bounds']['max'], [2, 1, 0])

    def test_gaussian_ply_labels_center_approximation(self):
        path = self.directory / 'cloud.ply'
        fields = 'x y z f_dc_0 f_dc_1 f_dc_2 scale_0 opacity rot_0'.split()
        path.write_text('ply\nformat ascii 1.0\nelement vertex 2\n' +
                        ''.join(f'property float {field}\n' for field in fields) +
                        'end_header\n0 0 0 1 0 0 0 1 1\n0 1 0 0 1 0 0 1 1\n')
        build(path, self.page)
        scene = decode_scene(self.page)
        self.assertIn('Gaussian centers', scene['note'])
        rgba = list(base64.b64decode(scene['meshes'][0]['colors']))
        self.assertEqual(rgba, [199, 128, 128, 255, 128, 199, 128, 255])

    def test_cdn_imports_depend_on_scene(self):
        for name, box in [('material_study.glb', False), ('synthetic.box.zip', True)]:
            with self.subTest(name=name):
                build(FIXTURES / name, self.page, runtime_source='cdn')
                html = self.page.read_text()
                imports = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html).group(1))['imports']
                self.assertEqual('three-impostor' in imports, box)
                self.assertEqual('three/tsl' in imports, box)
                self.assertEqual('ImpostorNodeMaterial' in html, box)
                self.assertNotIn('GLTFLoader', html)

    def test_default_output_and_path_from_another_directory(self):
        source = FIXTURES / 'material_study.glb'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'build_viewer.py'),
                                 str(source), '--path-only'], cwd=self.directory,
                                check=True, capture_output=True, text=True)
        self.assertEqual(Path(result.stdout.strip()), self.directory / (source.name + '.inspector.html'))
        self.assertTrue(Path(result.stdout.strip()).is_file())
        with self.assertRaisesRegex(ValueError, 'different file'):
            build(source, source)

    def test_limits_preserve_existing_output_on_failure(self):
        path = self.directory / 'bad.xyz'
        path.write_text('1 nan 3\n')
        self.page.write_text('last valid page')
        with self.assertRaisesRegex(ValueError, 'XYZ'):
            build(path, self.page)
        with self.assertRaisesRegex(ValueError, 'positive'):
            build(path, self.page, max_points=0)
        self.assertEqual(self.page.read_text(), 'last valid page')

    def test_box_face_limit_only_affects_proxy(self):
        source = FIXTURES / 'synthetic.box.zip'
        stats = build(source, self.page, max_triangles=3)
        self.assertEqual(stats['triangles'], 12)
        scene = decode_scene(self.page)
        for mesh in scene['meshes']:
            count = len(base64.b64decode(mesh['indices'])) // 12
            self.assertLessEqual(count, 3)
            self.assertGreater(count, 0)

if __name__ == '__main__':
    unittest.main()
