"""Evaluate a static USD stage into the shared Mesh / Points scene representation."""
import io
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
import trimesh
from pxr import Ar, Usd, UsdGeom, UsdShade


def triangulate(points, counts, indices, holes):
    """Return triangle face-corner indices so face-varying UV/color seams survive."""
    if sum(counts) != len(indices) or (len(indices) and (min(indices) < 0 or max(indices) >= len(points))):
        raise ValueError('USD mesh has invalid face indices')
    if not holes and np.all(counts == 3):
        return np.arange(len(indices), dtype=np.int64).reshape(-1, 3)
    triangles = []
    offset = 0
    for face, count in enumerate(counts):
        corners = np.arange(offset, offset + count)
        offset += count
        if face in holes or count < 3:
            continue
        if count == 3:
            triangles.append(corners)
            continue
        # Newell normal determines the most stable 2D projection of this face.
        poly = points[indices[corners]]
        normal = np.cross(poly, np.roll(poly, -1, axis=0)).sum(axis=0)
        xy = np.delete(poly, np.argmax(np.abs(normal)), axis=1)
        e = np.roll(xy, -1, axis=0) - xy
        def cross(u, v):
            return u[..., 0]*v[..., 1] - u[..., 1]*v[..., 0]
        turn = cross(e, np.roll(e, -1, axis=0))
        if turn.min() >= 0 or turn.max() <= 0:
            triangles.extend(np.column_stack((np.full(count-2, corners[0]), corners[1:-1], corners[2:])))
            continue
        sign = np.sign(cross(xy, np.roll(xy, -1, axis=0)).sum())
        remaining = list(range(count))
        while len(remaining) > 3:
            for i, b in enumerate(remaining):
                a, c = remaining[i-1], remaining[(i+1) % len(remaining)]
                ab, bc, ca = xy[b]-xy[a], xy[c]-xy[b], xy[a]-xy[c]
                if sign*cross(ab, bc) <= 0:
                    continue
                other = xy[[v for v in remaining if v not in (a, b, c)]]
                if np.any((sign*cross(ab, other-xy[a]) >= 0) &
                          (sign*cross(bc, other-xy[b]) >= 0) &
                          (sign*cross(ca, other-xy[c]) >= 0)):
                    continue
                triangles.append(corners[[a, b, c]])
                remaining.pop(i)
                break
            else:
                raise ValueError('USD face is degenerate or self-intersecting')
        triangles.append(corners[remaining])
    return np.asarray(triangles, dtype=np.int64).reshape(-1, 3)


def primvar(mesh, name, time, indices, counts):
    var = UsdGeom.PrimvarsAPI(mesh).FindPrimvarWithInheritance(name)
    if not var:
        return None
    value = var.ComputeFlattened(time)
    if value is None or not len(value):
        return None
    values = np.asarray(value)
    interpolation = var.GetInterpolation()
    if interpolation == 'constant':
        return np.repeat(values[:1], len(indices), axis=0)
    if interpolation == 'uniform':
        return np.repeat(values, counts, axis=0)
    if interpolation == 'faceVarying':
        return values
    return values[indices]


def preview_material(prim, time, directory):
    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    if not material:
        return None
    shader, _, _ = material.ComputeSurfaceSource()
    if not shader or shader.GetIdAttr().Get() != 'UsdPreviewSurface':
        return None
    def value(name, default):
        item = shader.GetInput(name)
        val = item.Get(time) if item else None
        return default if val is None else val
    diffuse = shader.GetInput('diffuseColor')
    texture = None
    if diffuse and diffuse.HasConnectedSource():
        node, _, _ = diffuse.GetConnectedSource()
        source = UsdShade.Shader(node.GetPrim())
        if source.GetIdAttr().Get() == 'UsdUVTexture':
            asset = source.GetInput('file').Get(time)
            if asset and asset.resolvedPath:
                resolved = asset.resolvedPath
                file = Path(resolved.split('[')[0]).resolve()
                if file.is_relative_to(directory):
                    stream = Ar.GetResolver().OpenAsset(Ar.ResolvedPath(resolved))
                    if stream and stream.GetSize() <= 512*1024*1024:
                        with Image.open(io.BytesIO(stream.GetBuffer())) as png:
                            texture = png.convert('RGBA')
    return trimesh.visual.material.PBRMaterial(
        name=material.GetPrim().GetName(),
        baseColorFactor=[*value('diffuseColor', [1, 1, 1]), value('opacity', 1)],
        baseColorTexture=texture, metallicFactor=value('metallic', 0),
        roughnessFactor=value('roughness', .5), emissiveFactor=value('emissiveColor', [0, 0, 0]),
        alphaMode='BLEND' if value('opacity', 1) < 1 else 'OPAQUE', doubleSided=True)


def mesh_geometry(prim, time, directory):
    mesh = UsdGeom.Mesh(prim)
    points = np.asarray(mesh.GetPointsAttr().Get(time), dtype=float)
    counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get(time), dtype=np.int64)
    indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get(time), dtype=np.int64)
    corners = triangulate(points, counts, indices, set(mesh.GetHoleIndicesAttr().Get(time) or []))
    if not len(corners):
        return None
    if mesh.GetOrientationAttr().Get(time) == 'leftHanded':
        corners = corners[:, ::-1]
    material = preview_material(prim, time, directory)
    uv = primvar(mesh, 'st', time, indices, counts)
    colors = primvar(mesh, 'displayColor', time, indices, counts) if material is None else None
    if uv is None and colors is None:
        result = trimesh.Trimesh(vertices=points, faces=indices[corners], process=False)
    else:
        # Vertices split only where per-corner attributes differ.
        attrs = [indices.reshape(-1, 1)]
        if uv is not None:
            attrs.append(uv)
        if colors is not None:
            attrs.append(colors)
        _, unique, inverse = np.unique(np.column_stack(attrs), axis=0, return_index=True, return_inverse=True)
        result = trimesh.Trimesh(vertices=points[indices[unique]], faces=inverse[corners], process=False)
        if uv is not None:
            uv = uv[unique]
        if colors is not None:
            result.visual.vertex_colors = np.rint(np.clip(colors[unique], 0, 1)*255).astype(np.uint8)
    if material is not None:
        result.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    return result


def usd_scene(path):
    if path.suffix.lower() == '.usdz':
        with zipfile.ZipFile(path) as archive:
            if sum(f.file_size for f in archive.infolist()) > 512*1024*1024:
                raise ValueError('Uncompressed USDZ exceeds 512 MiB')
    stage = Usd.Stage.Open(str(path))
    time = Usd.TimeCode(stage.GetStartTimeCode())
    transforms = UsdGeom.XformCache(time)
    up = np.eye(4)
    if UsdGeom.GetStageUpAxis(stage) == 'Z':
        up = trimesh.transformations.rotation_matrix(-np.pi/2, [1, 0, 0])
    up[:3, :3] *= UsdGeom.GetStageMetersPerUnit(stage)
    scene = trimesh.Scene()
    scene.units = 'meters'
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        imageable = UsdGeom.Imageable(prim)
        if not imageable or imageable.ComputeVisibility(time) == 'invisible' or imageable.ComputePurpose() == 'guide':
            continue
        kind = prim.GetTypeName()
        if kind == 'Mesh':
            result = mesh_geometry(prim, time, path.parent)
        elif kind == 'Points':
            positions = UsdGeom.Points(prim).GetPointsAttr().Get(time)
            colors = UsdGeom.PrimvarsAPI(prim).GetPrimvar('displayColor').ComputeFlattened(time)
            rgb = None
            if colors is not None and len(colors) in (1, len(positions)):
                rgb = np.broadcast_to(np.asarray(colors), (len(positions), 3))
                rgb = np.rint(np.clip(rgb, 0, 1)*255).astype(np.uint8)
            result = trimesh.points.PointCloud(np.asarray(positions), colors=rgb)
        elif kind in ('Cube','Sphere','Cylinder','Cone'):
            if kind == 'Cube':
                result = trimesh.creation.box(extents=[UsdGeom.Cube(prim).GetSizeAttr().Get(time)]*3)
            elif kind == 'Sphere':
                result = trimesh.creation.icosphere(radius=UsdGeom.Sphere(prim).GetRadiusAttr().Get(time))
            else:
                shape = getattr(UsdGeom, kind)(prim)
                height = shape.GetHeightAttr().Get(time)
                result = getattr(trimesh.creation, kind.lower())(radius=shape.GetRadiusAttr().Get(time), height=height)
                if kind == 'Cone':
                    result.apply_translation([0, 0, -height/2])
                axis = shape.GetAxisAttr().Get(time)
                result.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], np.eye(3)['XYZ'.index(axis)]))
            mat = preview_material(prim, time, path.parent)
            if mat is not None:
                result.visual = trimesh.visual.TextureVisuals(material=mat)
            else:
                color = UsdGeom.Gprim(prim).GetDisplayColorAttr().Get(time)
                if color:
                    result.visual.vertex_colors = np.rint(np.clip(color[0], 0, 1)*255).astype(np.uint8)
        else:
            continue
        if result is None:
            continue
        name = str(prim.GetPath())
        transform = up @ np.array(transforms.GetLocalToWorldTransform(prim)).T
        scene.add_geometry(result, node_name=name, geom_name=name, transform=transform)
    if not scene.geometry:
        raise ValueError('USD stage contains no supported visible mesh, primitive or point cloud')
    return scene
