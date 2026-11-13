#!/usr/bin/env python3
"""Build a portable HTML inspector with a runtime selected from the asset contents."""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import os
import shutil
import subprocess
import tempfile
import sys
import zipfile
import zlib

from viewer_dependencies import MissingViewerDependency

import numpy as np
from PIL import Image

VERSION = 1
FORMATS = {'.glb', '.gltf', '.obj', '.stl', '.ply', '.3mf', '.off', '.xyz', '.dae'}
FACES = ['+X', '-X', '+Y', '-Y', '+Z', '-Z']
CHANNEL_MAPS = {'colorMap': 'Base color', 'normalMap': 'Normal', 'intervalMap': 'Intervals',
                'rangeMap': 'Depth range', 'materialMap': 'R: roughness · G: metallic · B: AO',
                'emissiveMap': 'Emissive', 'baseColor': 'Unedited color'}
MAX_INPUT = 512 * 1024 * 1024
MAX_TEXTURE_SIZE = 2048


def buffer64(arr, dtype):
    return base64.b64encode(np.ascontiguousarray(arr, dtype=dtype).tobytes()).decode('ascii')


def png_uri(image: Image.Image, cap=MAX_TEXTURE_SIZE):
    im = image.convert('RGBA')
    if max(im.size) > cap:
        im.thumbnail((cap, cap), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    im.save(output, format='PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii'), im.size


def finite(array):
    return bool(np.isfinite(array).all())


def clean_name(name: str, limit=100):
    return re.sub(r'[\x00-\x1f\x7f]', '', str(name))[:limit].strip() or 'Unnamed'


def convert_texture(image, name, role, textures, *, max_size=MAX_TEXTURE_SIZE, channels=None):
    uri, size = png_uri(image, max_size)
    index = len(textures)
    textures.append(dict(name=clean_name(name), role=role, width=size[0], height=size[1],
                         format='PNG', channels=channels or 'RGBA', dataUri=uri))
    return index


def quantized_color(value):
    a = np.asarray(value, dtype=np.float64).reshape(-1)
    if len(a) < 3:
        return [1, 1, 1, 1]
    if np.max(a) > 1:
        a = a / 255
    return np.clip(list(a[:4]) + [1] * (4-len(a[:4])), 0, 1).tolist()


def point_object(name, vertices, colors, limit):
    points = np.asarray(vertices, dtype=np.float32)
    if not len(points) or not finite(points):
        raise ValueError('Point coordinates must be finite and nonempty')
    # Evenly sample the full input, including its endpoints.
    selection = slice(None) if len(points) <= limit else np.linspace(
        0, len(points) - 1, limit, dtype=np.int64)
    obj = dict(name=clean_name(name), primitive='points', material=0,
               positions=buffer64(points[selection], '<f4'))
    if colors is not None and len(colors) == len(points):
        rgba = np.asarray(colors, dtype=np.uint8)
        if rgba.shape == (len(points), 3):
            rgba = np.column_stack((rgba, np.full(len(points), 255, dtype=np.uint8)))
        if rgba.shape == (len(points), 4):
            obj['colors'] = buffer64(rgba[selection], 'u1')
    return obj


def point_colors(mesh):
    # Gaussian-splat PLY often stores only SH coefficients, scale and opacity.
    # Its center preview can still show the actual degree-zero color.
    vertex = mesh.metadata.get('_ply_raw', {}).get('vertex', {})
    fields = vertex.get('properties', {})
    splats = all(key in fields for key in ('f_dc_0', 'f_dc_1', 'f_dc_2', 'scale_0', 'rot_0', 'opacity'))
    if splats:
        data = vertex['data']
        dc = np.column_stack([data['f_dc_' + str(i)] for i in range(3)])
        if not finite(dc):
            raise ValueError('Gaussian color coefficients must be finite')
        colors = np.rint(np.clip(0.5 + 0.28209479177387814 * dc, 0, 1) * 255)
        return colors.astype(np.uint8), True
    return mesh.colors, False


def xyz_scene(path, point_limit):
    # XYZ has no header. Extra columns are accepted only in the XYZRGB[A]
    # layouts to avoid silently treating normals or intensity as a color.
    values = np.loadtxt(path, dtype=np.float64, ndmin=2)
    if values.shape[1] not in (3, 6, 7) or not len(values) or not finite(values):
        raise ValueError('Expected XYZ coordinates, optionally followed by RGB or RGBA')
    points = values[:, :3]
    colors = values[:, 3:]
    if colors.size:
        if colors.min() < 0 or colors.max() > 255:
            raise ValueError('XYZ colors must be in the range 0–1 or 0–255')
        colors = np.round(colors * (255 if colors.max() <= 1 else 1))
    obj = point_object(path.stem, points, colors if colors.size else None, point_limit)
    return finalize_scene(path.stem, 'XYZ', [obj], [], [], description='Point cloud',
                          previewType='points', unit='model', fixed_bounds=(points.min(axis=0), points.max(axis=0)),
                          original=dict(vertices=len(points), triangles=0))


def glb_scene(path, *, limit=250_000, point_limit=500_000, texture_size=MAX_TEXTURE_SIZE, loaded_scene=None):
    try:
        import trimesh
    except ImportError as exc:
        raise SystemExit('Missing trimesh. Install with: pip install numpy pillow trimesh') from exc
    if path.stat().st_size > MAX_INPUT:
        raise ValueError('Input file exceeds the 512 MiB limit')
    loaded = loaded_scene if loaded_scene is not None else trimesh.load(str(path), force='scene', process=False)
    if isinstance(loaded, trimesh.Trimesh):
        scene = trimesh.Scene(loaded)
    else:
        scene = loaded
    textures, materials, meshes = [], [], []
    material_cache = {}
    has_splat_centers = False
    source_vertex_total = 0
    source_triangle_total = 0
    for node_name in sorted(scene.graph.nodes_geometry):
        transform, geometry_name = scene.graph.get(node_name)
        mesh = scene.geometry[geometry_name]
        is_cloud = isinstance(mesh, trimesh.points.PointCloud)
        if not is_cloud and not isinstance(mesh, trimesh.Trimesh):
            continue
        if not len(mesh.vertices) or (not is_cloud and not len(mesh.faces)):
            continue
        v = np.asarray(mesh.vertices, dtype=np.float64)
        transform = np.asarray(transform, dtype=np.float64)
        vertices = np.c_[v, np.ones(len(v))] @ transform.T
        vertices = vertices[:, :3]
        if not finite(vertices):
            raise ValueError('Mesh coordinates must be finite')
        if is_cloud:
            colors, gaussian = point_colors(mesh)
            has_splat_centers |= gaussian
            obj = point_object(node_name, vertices, colors, point_limit)
            if 'point-color' not in material_cache:
                material_cache['point-color'] = len(materials)
                materials.append(dict(name='Point colors', baseColor=[1, 1, 1, 1], alphaMode='OPAQUE'))
            obj['material'] = material_cache['point-color']
            meshes.append(obj)
            source_vertex_total += len(vertices)
            continue
        # Material is keyed by node AND material object; submeshes can reuse.
        visual = mesh.visual
        matobj = getattr(visual, 'material', None)
        key = id(matobj) if matobj is not None else geometry_name + '_none'
        if key not in material_cache:
            name = clean_name(getattr(matobj, 'name', '') or geometry_name)
            base = quantized_color(getattr(matobj, 'baseColorFactor', None) if getattr(matobj, 'baseColorFactor', None) is not None else
                                   getattr(matobj, 'diffuse', [255,255,255,255]))
            material = dict(name=name, baseColor=base, metallic=float(getattr(matobj,'metallicFactor',0) or 0),
                            roughness=float(getattr(matobj,'roughnessFactor',1) if getattr(matobj,'roughnessFactor',None) is not None else 1),
                            alphaMode=str(getattr(matobj,'alphaMode','OPAQUE') or 'OPAQUE'),
                            alphaCutoff=float(getattr(matobj,'alphaCutoff',.5) or .5),
                            emissiveFactor=quantized_color(getattr(matobj,'emissiveFactor',None)
                                if getattr(matobj,'emissiveFactor',None) is not None else [0,0,0])[:3],
                            baseColorTexture=-1, normalTexture=-1, metallicRoughnessTexture=-1,
                            emissiveTexture=-1, occlusionTexture=-1,
                            doubleSided=bool(getattr(matobj,'doubleSided',True)))
            for attr, dest, role in [('baseColorTexture','baseColorTexture','Base color'),
                                     ('normalTexture','normalTexture','Normal'),
                                     ('metallicRoughnessTexture','metallicRoughnessTexture','Metallic / roughness'),
                                     ('emissiveTexture','emissiveTexture','Emissive'),
                                     ('occlusionTexture','occlusionTexture','AO')]:
                img = getattr(matobj, attr, None)
                if isinstance(img, Image.Image):
                    material[dest] = convert_texture(img, f'{name} · {role}', role, textures, max_size=texture_size)
            # OBJ SimpleMaterial uses .image, not .baseColorTexture
            img = getattr(matobj, 'image', None)
            if material['baseColorTexture'] == -1 and isinstance(img, Image.Image):
                material['baseColorTexture'] = convert_texture(img, name+' · Albedo', 'Base color', textures, max_size=texture_size)
            material_cache[key] = len(materials)
            materials.append(material)
        mi = material_cache[key]
        idx = np.asarray(mesh.faces, dtype=np.uint32).reshape(-1)
        source_vertex_total += len(v)
        source_triangle_total += len(idx)//3
        vertex_normal = np.asarray(mesh.vertex_normals, dtype=np.float64)
        normal_matrix = np.linalg.pinv(transform[:3,:3]).T
        vertex_normal = vertex_normal @ normal_matrix.T
        vertex_normal /= np.maximum(np.linalg.norm(vertex_normal,axis=1,keepdims=True),1e-8)
        if not finite(vertex_normal):
            vertex_normal[:] = [0,1,0]
        uv = getattr(visual, 'uv', None)
        has_uv = uv is not None and len(uv) == len(v)
        if not has_uv:
            uv = np.zeros((len(v),2), dtype=np.float32)
        else:
            uv = np.asarray(uv, dtype=np.float32)
        if visual.kind == 'vertex':
            colors = np.asarray(visual.vertex_colors, dtype=np.uint8)
            if colors.shape[1] == 3:
                colors = np.c_[colors,np.full(len(v),255,dtype=np.uint8)]
        elif visual.kind == 'face' and len(visual.face_colors) == len(mesh.faces):
            # Expand vertices for per-face paints (PLY/OBJ colour variants).
            fids = np.asarray(mesh.faces, dtype=np.uint32).reshape(-1)
            colors = np.repeat(np.asarray(visual.face_colors,dtype=np.uint8),3,axis=0)
            vertices,vertex_normal,uv = vertices[fids],vertex_normal[fids],uv[fids]
            idx = np.arange(len(vertices),dtype=np.uint32)
        else:
            colors = np.full((len(vertices),4),255,dtype=np.uint8)
        if np.linalg.det(transform[:3, :3]) < 0:
            # Baking a reflection into positions reverses the geometric winding.
            idx = idx.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1)
        # WebGL2 multiplies true vertex colors by the texture. Canvas2D uses
        # a separate UV-sampled color approximation when textures are present.
        webgl_colors = np.array(colors,copy=True)
        texidx = materials[mi]['baseColorTexture']
        if texidx >= 0:
            img = getattr(matobj,'baseColorTexture',None)
            if img is None: img = getattr(matobj,'image',None)
            if isinstance(img,Image.Image):
                pic = np.array(img.convert('RGBA'))
                px = np.clip((uv[:,0] % 1)*(pic.shape[1]-1),0,pic.shape[1]-1).astype(int)
                py = np.clip((1-uv[:,1] % 1)*(pic.shape[0]-1),0,pic.shape[0]-1).astype(int)
                colors = (colors.astype('float32')*pic[py,px].astype('float32')/255).astype('uint8')
        # Limit using deterministic face stride (no random sampling).
        if len(idx)//3 > limit:
            step = int(np.ceil((len(idx)//3)/limit))
            faces = idx.reshape(-1, 3)[::step]
            used, inverse = np.unique(faces.ravel(), return_inverse=True)
            idx = inverse.astype(np.uint32)
            vertices, vertex_normal, uv, colors, webgl_colors = (vertices[used],vertex_normal[used],
                uv[used],colors[used],webgl_colors[used])
        obj = dict(name=clean_name(node_name), material=mi, positions=buffer64(vertices, '<f4'),
                   indices=buffer64(idx, '<u4'), normals=buffer64(vertex_normal, '<f4'))
        if has_uv:
            obj['uv'] = buffer64(uv, '<f4')
        if np.any(webgl_colors != 255):
            obj['colors'] = buffer64(webgl_colors, 'u1')
        if not np.array_equal(colors, webgl_colors):
            obj['fallbackColors'] = buffer64(colors, 'u1')
        meshes.append(obj)
    if not meshes:
        raise ValueError('No triangle meshes or point clouds were found in the asset')
    point_only = all(obj.get('primitive') == 'points' for obj in meshes)
    return finalize_scene(path.stem, path.suffix.lstrip('.').upper(), meshes, materials, textures,
                          description='Gaussian centers' if has_splat_centers else 'Point cloud' if point_only else 'Mesh asset',
                          note='Gaussian centers and DC colors only. Splat scale, opacity and view-dependent lighting are omitted.' if has_splat_centers else None,
                          previewType='points' if point_only else 'mesh', unit=scene.units or 'model',
                          fixed_bounds=scene.bounds, original=dict(vertices=source_vertex_total, triangles=source_triangle_total))


def image_from_half(data,desc,*, color=False):
    w,h=desc['width'],desc['height']
    if w<1 or h<1 or w*h>MAX_INPUT//8:
        raise ValueError('Unreasonable atlas dimensions')
    dtype = '<f2' if desc['dtype']=='float16' else 'u1'
    arr=np.frombuffer(data,dtype=dtype)
    if arr.size!=w*h*4: raise ValueError('Mismatched map byte count')
    arr=arr.reshape(h,w,4).astype(np.float32)
    if desc['dtype'] == 'uint8':arr/=255
    a=np.clip(np.nan_to_num(arr[:,:,3],nan=0),0,1)
    rgb=np.clip(np.nan_to_num(arr[:,:,:3],nan=0,posinf=1,neginf=0),0,1)
    if color:
        rgb=np.clip(rgb/np.maximum(a[:,:,None],.00001),0,1)
        rgb=np.where(rgb<=.0031308,rgb*12.92,1.055*np.power(rgb,1/2.4)-.055)
    rgba=np.concatenate([rgb,a[:,:,None]],axis=2)
    rgba=(np.flipud(rgba)*255+.5).astype(np.uint8)
    return Image.fromarray(rgba,'RGBA')


def box_scene(path, *, grid=72, texture_size=MAX_TEXTURE_SIZE, limit=250_000, native=True):
    if not 8<=grid<=256:
        raise ValueError('Box surface grid must be 8–256')
    if path.stat().st_size>MAX_INPUT:
        raise ValueError('Box ZIP exceeds the 512 MiB limit')
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist()
        if len(entries)>400 or sum(i.file_size for i in entries)>MAX_INPUT:
            raise ValueError('Archive is too large')
        if any(i.filename.startswith('/') or '..' in Path(i.filename).parts or '\\' in i.filename for i in entries):
            raise ValueError('Unsafe ZIP member path')
        m=json.loads(archive.read('manifest.json'))
        if m.get('schemaVersion')!=1 or m.get('layout')!='box' or m.get('faceOrder')!=FACES:
            raise ValueError('Not a supported six-face Box ZIP')
        r=int(m['resolution'])
        if not 8<=r<=4096:
            raise ValueError('Unsupported Box resolution')
        dims=np.array([m['bakeBox']['min'],m['bakeBox']['max']],dtype=np.float64)
        if dims.shape!=(2,3) or not finite(dims) or (dims[1]<=dims[0]).any():
            raise ValueError('Invalid Box bake bounds')
        textures=[]
        ids={}
        raw_native={}
        color_atlas=None
        if native and any(name not in m.get('textures',{}) for name in ('colorMap','normalMap','intervalMap','rangeMap')):
            raise ValueError('Native Box requires color, normal, interval and range maps')
        for name in ['colorMap','normalMap','intervalMap','rangeMap','materialMap','emissiveMap']:
            desc=m.get('textures',{}).get(name)
            if not desc:continue
            data=archive.read(desc['path'])
            if hashlib.sha256(data).hexdigest()!=desc['sha256']:
                raise ValueError('Box map checksum mismatch: '+name)
            if native:
                # Preserve original RGBA16F atlas bytes for the upstream
                # Three.js/three-impostor raymarcher. PNGs below are just for
                # the inspector's texture thumbnails.
                raw_native[desc['path']]=base64.b64encode(data).decode('ascii')
            if name=='colorMap':
                color_atlas=np.frombuffer(data,dtype='<f2').reshape(2*r,3*r,4).astype(np.float32)
            im=image_from_half(data,desc,color=name in ('colorMap','emissiveMap'))
            ids[name]=convert_texture(im,name,CHANNEL_MAPS[name],textures,max_size=texture_size)
        if color_atlas is None:
            raise ValueError('Missing Box colorMap')
        base=m.get('baseColor')
        if base and base.get('sha256')!=m['textures']['colorMap']['sha256']:
            data=archive.read(base['path'])
            if hashlib.sha256(data).hexdigest()!=base['sha256']:
                raise ValueError('Base color checksum mismatch')
            ids['baseColor']=convert_texture(image_from_half(data,base,color=True),'baseColor',CHANNEL_MAPS['baseColor'],textures,max_size=texture_size)
        for face in FACES:
            item=m['faces'][face]
            g=item.get('guide')
            if g and g in archive.namelist():
                raw=archive.read(g)
                if item.get('guideSha256') and hashlib.sha256(raw).hexdigest()!=item['guideSha256']:
                    raise ValueError('Box guide checksum mismatch: '+face)
                im=Image.open(io.BytesIO(raw))
                convert_texture(im,'Guide '+face,'Orthographic guide',textures,max_size=texture_size)
            depth_path=item.get('depth')
            if not depth_path or depth_path not in archive.namelist():
                raise ValueError('Missing Box depth: '+face)
            depth=archive.read(depth_path)
            if len(depth)!=r*r*2:
                raise ValueError('Invalid Box depth size: '+face)
            if item.get('depthSha256') and hashlib.sha256(depth).hexdigest()!=item['depthSha256']:
                raise ValueError('Box depth checksum mismatch: '+face)
        mesh_data=[]
        selected = np.linspace(1,r-2,min(grid,r)).round().astype(np.int32)
        # Sampling on a grid; consistent with storage: raw atlas row 0 = shader V=0.
        for fi,face in enumerate(FACES):
            f=m['faces'][face]
            depth=np.frombuffer(archive.read(f['depth']),dtype='<f2').reshape(r,r).astype(np.float32)
            atlas=color_atlas[fi//3*r:(fi//3+1)*r,fi%3*r:(fi%3+1)*r]
            vert,uvs,col=[],[],[]
            index=np.full((len(selected),len(selected)),-1,np.int32)
            depth_index=np.full_like(index,np.nan,dtype=np.float32)
            for yi,y in enumerate(selected):
                for xi,x in enumerate(selected):
                    delta=float(depth[r-1-y,x]);rgba=atlas[y,x]
                    if not np.isfinite(delta) or delta<0 or delta>1 or rgba[3]<.04:continue
                    u=(x+.5)/r;v=(y+.5)/r
                    if face=='+X':pos=[1-delta,v,1-u]
                    elif face=='-X':pos=[delta,v,u]
                    elif face=='+Y':pos=[u,1-delta,1-v]
                    elif face=='-Y':pos=[u,delta,v]
                    elif face=='+Z':pos=[u,v,1-delta]
                    else:pos=[1-u,v,delta]
                    xyz=dims[0]+np.clip(pos,0,1)*(dims[1]-dims[0])
                    texuv=[(fi%3+u)/3,(fi//3+v)/2]
                    index[yi,xi]=len(vert)
                    depth_index[yi,xi]=delta
                    vert.append(xyz);uvs.append(texuv)
                    color=np.clip(rgba[:3]/max(.001,float(rgba[3])),0,1)
                    srgb=np.where(color<=.0031308,12.92*color,1.055*np.power(color,1/2.4)-.055)
                    col.append(np.r_[srgb,rgba[3]]*255)
            tris=[]
            for y in range(len(selected)-1):
                for x in range(len(selected)-1):
                    verts=[index[y,x],index[y,x+1],index[y+1,x],index[y+1,x+1]]
                    zz=[depth_index[y,x],depth_index[y,x+1],depth_index[y+1,x],depth_index[y+1,x+1]]
                    if min(verts)<0 or max(zz)-min(zz)>.18:continue
                    a,b,c,d=verts
                    tris.extend([(a,b,c),(b,d,c)])
            if not tris:continue
            vertices=np.asarray(vert,dtype=np.float32);faces=np.asarray(tris,dtype=np.uint32)
            if len(faces) > limit:
                faces = faces[::int(np.ceil(len(faces) / limit))]
                used, inverse = np.unique(faces.ravel(), return_inverse=True)
                vertices = vertices[used]
                uvs = np.asarray(uvs)[used]
                col = np.asarray(col)[used]
                faces = inverse.astype(np.uint32).reshape(-1, 3)
            normals=np.zeros_like(vertices)
            for triangle in faces:
                a,b,c=vertices[triangle]
                n=np.cross(b-a,c-a)
                for t in triangle:normals[t]+=n
            nlen=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-9)
            normals=normals/nlen
            mesh_data.append(dict(name=face+' surface',material=0,positions=buffer64(vertices,np.float32),
                                  normals=buffer64(normals,np.float32),uv=buffer64(uvs,np.float32),
                                  indices=buffer64(faces.reshape(-1),np.uint32),
                                  fallbackColors=buffer64(np.clip(col,0,255),np.uint8)))
        if not mesh_data:raise ValueError('No visible Box surface samples')
        material=dict(name='Box atlas',baseColor=[1,1,1,1],metallic=0,roughness=1,
                      metallicSource='Material Map · G' if 'metalness' in m.get('maps',[]) else None,
                      roughnessSource='Material Map · R' if 'roughness' in m.get('maps',[]) else None,
                      alphaMode='BLEND',baseColorTexture=ids['colorMap'],normalTexture=ids.get('normalMap',-1),
                      metallicRoughnessTexture=ids.get('materialMap',-1),emissiveTexture=ids.get('emissiveMap',-1),
                      occlusionTexture=-1,doubleSided=True)
        # Source proxy counts, if trimesh can inspect its native GLB.
        original={}
        try:
            import trimesh
            proxy=trimesh.load(io.BytesIO(archive.read(m['proxy'])),file_type='glb',force='scene',process=False)
            original=dict(vertices=sum(len(x.vertices) for x in proxy.geometry.values()),
                          triangles=sum(len(x.faces) for x in proxy.geometry.values()))
        except Exception: original={}
        out=finalize_scene(path.name.removesuffix('.box.zip'),'Box impostor ZIP',mesh_data,[material],textures,
                           description='Native ray-marched Box' if native else 'Derived surface mesh',
                           unit='bake unit',original=original,
                           note=('Native three-impostor ray marching via Three.js. If WebGL2 is unavailable, a sampled surface mesh is shown instead.'
                                 if native else 'Preview geometry is sampled from Box depth guides, not the native three-impostor shader.'),
                           previewType='native-box' if native else 'surface', fixed_bounds=dims)
        out['assetId']=m.get('asset_id')
        out['resolution']=r
        if native:
            out['nativeBox']={
                'manifest': {key:m[key] for key in ('schemaVersion','layout','resolution','bakeBox','maps','textures')},
                'files':raw_native,
            }
        return out


def finalize_scene(name,fmt,meshes,materials,textures,*,description,unit,original,note=None,previewType='mesh',fixed_bounds=None):
    if fixed_bounds is None:
        allp=[np.frombuffer(base64.b64decode(m['positions']),dtype='<f4').reshape(-1,3) for m in meshes]
        mins=np.min([p.min(axis=0) for p in allp],axis=0)
        maxs=np.max([p.max(axis=0) for p in allp],axis=0)
    else:mins,maxs=fixed_bounds
    if not materials:materials=[dict(name='Default',baseColor=[1,1,1,1],metallic=0,roughness=1,
                                    baseColorTexture=-1,normalTexture=-1,alphaMode='OPAQUE')]
    return dict(version=VERSION,name=clean_name(name),format=fmt,description=description,
                unit=unit,original=original or {},bounds={'min':np.asarray(mins).tolist(),'max':np.asarray(maxs).tolist()},
                previewType=previewType,note=note,meshes=meshes,materials=materials,textures=textures)


def gltf_or_mesh_scene(path, max_triangles, max_points, max_texture, renderer):
    packed, stats = None, None
    if path.suffix.lower() in ('.glb', '.gltf'):
        from gltf_scene import prepare_gltf
        packed, stats = prepare_gltf(path, max_texture)
    options = dict(limit=max_triangles, point_limit=max_points, texture_size=max_texture)
    if packed is not None:
        # The Canvas2D proxy and the native viewer must see the same decoded geometry.
        with tempfile.TemporaryDirectory(prefix='3d-inspector-gltf-') as directory:
            converted = Path(directory) / 'model.glb'
            converted.write_bytes(packed)
            scene = glb_scene(converted, **options)
            scene.update(name=clean_name(path.stem), format=path.suffix[1:].upper())
    else:
        scene = glb_scene(path, **options)
    if stats is not None and renderer == 'native':
        scene['nativeGltf'] = dict(glb=base64.b64encode(packed).decode('ascii'), stats=stats)
        scene['previewType'] = 'native-gltf'
    return scene


def blender_scene(path, max_triangles, max_points, max_texture, renderer):
    blender = shutil.which('blender')
    label = path.suffix[1:].upper()
    if not blender:
        raise ValueError(f'{label} input requires Blender on PATH. Alternatively, export the source as GLB.')
    import_script = Path(__file__).resolve().with_name('blender_export.py')
    with tempfile.TemporaryDirectory(prefix='3d-inspector-blender-') as folder:
        glb = Path(folder) / 'converted.glb'
        result = subprocess.run(
            [blender, '--background', '--factory-startup', '--disable-autoexec',
             '--threads', '1', '--python-exit-code', '1', '--python', str(import_script),
             '--', str(path), str(glb)],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode or not glb.is_file():
            detail = (result.stdout + result.stderr).strip()[-3000:]
            raise ValueError(f'Blender could not export {label}. ' + detail)
        scene = gltf_or_mesh_scene(glb, max_triangles, max_points, max_texture, renderer)
        scene.update(format=label, name=clean_name(path.stem))
        return scene


def build(input_file: Path, output_file: Path, *, title=None, grid=72, max_triangles=250_000,
          max_texture=MAX_TEXTURE_SIZE, renderer='native', runtime_source='embedded',
          max_points=500_000):
    input_file = input_file.expanduser().resolve()
    output_file = output_file.expanduser().resolve()
    if not input_file.is_file():
        raise ValueError('Input file does not exist: ' + str(input_file))
    if output_file == input_file or (output_file.exists() and input_file.samefile(output_file)):
        raise ValueError('Output must be a different file from the input')
    if min(max_triangles, max_texture, max_points) < 1:
        raise ValueError('Triangle, texture, and point limits must be positive')
    if input_file.stat().st_size > MAX_INPUT:
        raise ValueError('Input exceeds the 512 MiB limit')
    if renderer not in ('native','legacy'):
        raise ValueError('Renderer must be native or legacy')
    if runtime_source not in ('embedded','cdn'):
        raise ValueError('Runtime source must be embedded or cdn')
    suffix = input_file.suffix.lower()
    if suffix == '.3mf':
        with zipfile.ZipFile(input_file) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > MAX_INPUT:
                raise ValueError('Uncompressed 3MF exceeds the 512 MiB limit')
    if input_file.name.lower().endswith('.box.zip'):
        scene = box_scene(input_file, grid=grid, texture_size=max_texture, limit=max_triangles,
                          native=renderer=='native')
    elif suffix in ('.ply', '.splat'):
        from splat_scene import gaussian_ply, read_splats
        if suffix == '.splat' or gaussian_ply(input_file):
            scene = read_splats(input_file, max_points, renderer == 'native')
        else:
            scene = glb_scene(input_file, limit=max_triangles, point_limit=max_points, texture_size=max_texture)
    elif suffix == '.xyz':
        scene = xyz_scene(input_file, max_points)
    elif suffix in ('.usd', '.usda', '.usdc', '.usdz'):
        try:
            from usd_scene import usd_scene
        except ModuleNotFoundError as exc:
            if exc.name != 'pxr':
                raise
            raise MissingViewerDependency('usd-core') from exc
        scene = glb_scene(input_file, limit=max_triangles, point_limit=max_points, texture_size=max_texture,
                          loaded_scene=usd_scene(input_file))
        scene['unit'] = 'meters'
        scene['note'] = ('Static USD preview at the stage start time. Meshes, point clouds and common shape primitives '
                         'are shown. Subdivision, skinning, animated playback and shader graphs are not evaluated.')
    elif suffix in ('.stp', '.step', '.igs', '.iges', '.brep'):
        try:
            from cad_scene import cad_scene
        except ModuleNotFoundError as exc:
            if exc.name != 'OCP':
                raise
            raise MissingViewerDependency('OpenCASCADE') from exc
        scene = glb_scene(input_file, limit=max_triangles, point_limit=max_points, texture_size=max_texture,
                          loaded_scene=cad_scene(input_file))
        scene['unit'] = 'model units' if suffix == '.brep' else 'mm'
        scene['description'] = 'Tessellated CAD'
        scene['note'] = 'Tessellated CAD geometry. Counts describe the tessellation. Part colors and drafting annotations are omitted.'
    elif suffix in ('.fbx', '.blend'):
        scene = blender_scene(input_file, max_triangles, max_points, max_texture, renderer)
    elif suffix in FORMATS:
        scene = gltf_or_mesh_scene(input_file, max_triangles, max_points, max_texture, renderer)
    else:
        raise ValueError('Unsupported input format: ' + input_file.name)
    if title:scene['name']=clean_name(title)
    data=json.dumps(scene,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</script>','<\\/script>')
    compressed=zlib.compress(data.encode('utf-8'),level=9)
    payload=base64.b64encode(compressed).decode('ascii')
    assets = Path(__file__).resolve().parent.parent / 'assets'
    html = (assets / 'viewer.html').read_text(encoding='utf-8').replace('__SCENE_PAYLOAD__', payload)
    profile = 'native' if 'nativeBox' in scene else 'gltf' if 'nativeGltf' in scene else 'mesh'
    if 'nativeSplat' in scene:
        profile = scene['nativeSplat']['profile']
    code = ''
    if renderer == 'native':
        suffix = 'cdn.mjs' if runtime_source == 'cdn' else 'bundle.js'
        runtime = assets / f'{profile}-runtime.{suffix}'
        code = runtime.read_text(encoding='utf-8').replace('</script>', '<\\/script>')
    if renderer == 'native' and runtime_source == 'cdn':
        three = 'https://cdn.jsdelivr.net/npm/three@0.186.0/'
        modules = {'three': three + 'build/three.webgpu.js',
                   'three/webgpu': three + 'build/three.webgpu.js',
                   'three/addons/': three + 'examples/jsm/'}
        if profile in ('native', 'splat', 'splat-ply'):
            modules['three/tsl'] = three + 'build/three.tsl.js'
        if profile == 'native':
            modules['three-impostor'] = 'https://cdn.jsdelivr.net/npm/three-impostor@0.4.1/Impostor.js'
        imports = {'imports': modules}
        bootstrap=(
            '<script type="importmap">'+json.dumps(imports,separators=(',',':'))+'</script>\n'
            '<script>globalThis.InspectorRuntimeReady=new Promise(resolve=>{'
            'let settled=false;const timer=setTimeout(()=>{if(!settled){settled=true;resolve(false)}},16000);'
            'globalThis.__inspectorCDNReady={resolve:()=>{if(!settled){settled=true;clearTimeout(timer);resolve(true)}}};'
            '});</script>\n'
            '<script type="module">'+code+'</script>'
        )
        html=html.replace('<script>__NATIVE_RUNTIME_JS__</script>',bootstrap)
        html=html.replace('No network requests · Self-contained scene','CDN modules · Embedded scene data')
    else:
        html=html.replace('__NATIVE_RUNTIME_JS__',code)
    notices = (assets / 'THIRD_PARTY_LICENSES.txt').read_text(encoding='utf-8')
    if profile != 'native':
        notices = notices.partition('\nthree-impostor ')[0].rstrip()
    html = html.replace('__THIRD_PARTY_LICENSES__', notices.replace('-->', '-- >') if renderer == 'native' else 'Canvas 2D')
    output_file.parent.mkdir(parents=True, exist_ok=True)
    # Publish the complete file atomically; a failed write leaves an earlier viewer usable.
    with tempfile.TemporaryDirectory(dir=output_file.parent, prefix='.3d-inspector-') as folder:
        temp_path = Path(folder) / 'output.html'
        temp_path.write_text(html, encoding='utf-8')
        if output_file.is_file():
            temp_path.chmod(output_file.stat().st_mode & 0o777)
        os.replace(temp_path, output_file)
    fallback_vertices = sum(len(base64.b64decode(m['positions'])) // 12 for m in scene['meshes'])
    fallback_triangles = sum(len(base64.b64decode(m.get('indices', ''))) // 12 for m in scene['meshes'])
    native_box = 'nativeBox' in scene
    stats = scene.get('nativeGltf', {}).get('stats', {})
    has_proxy = native_box or bool(stats)
    return dict(file=str(output_file), size=output_file.stat().st_size,
                vertices=24 if native_box else stats.get('vertices', fallback_vertices),
                triangles=12 if native_box else stats.get('triangles', fallback_triangles),
                meshes=1 if native_box else stats.get('meshes', len(scene['meshes'])),
                materials=stats.get('materials', len(scene['materials'])), textures=len(scene['textures']),
                runtimeProfile=(('box' if profile == 'native' else profile) if renderer=='native' else 'canvas'),
                fallbackVertices=fallback_vertices if has_proxy else None,
                fallbackTriangles=fallback_triangles if has_proxy else None,
                sourceVertices=scene['original'].get('vertices'),
                sourceTriangles=scene['original'].get('triangles'),
                renderer='Three.js / three-impostor' if native_box else ('Three.js' if renderer=='native' else 'legacy'),
                mode=scene['previewType'])


def main(argv=None):
    parser=argparse.ArgumentParser(description='Build a standalone, offline 3D-Inspector HTML')
    parser.add_argument('input',type=Path,help='Model: GLB, glTF, OBJ, STL, PLY, SPLAT, 3MF, OFF, XYZ, DAE, STEP, IGES, BREP, USD/USDA/USDC/USDZ, FBX/BLEND (via Blender) or .box.zip')
    parser.add_argument('-o','--output',type=Path,help='Output file (default: INPUT_NAME.inspector.html in the current directory)')
    parser.add_argument('--title',help='Optional display title')
    parser.add_argument('--grid',type=int,default=72,help='Box ZIP sampling grid 8–256 (default 72)')
    parser.add_argument('--max-triangles',type=int,default=250_000,help='Per mesh face cap')
    parser.add_argument('--max-points',type=int,default=500_000,help='Per point-cloud vertex cap')
    parser.add_argument('--path-only',action='store_true',help='Print only the absolute output path')
    parser.add_argument('--max-texture',type=int,default=2048,help='Texture longest side in px')
    parser.add_argument('--runtime-source',choices=['embedded','cdn'],default='embedded',
                        help='embedded (offline) or CDN ESM imports; model data is always embedded')
    parser.add_argument('--renderer',choices=['native','legacy'],default='native',
                        help='native: Three.js and native Box ray marching; legacy: approximate fallback')
    args=parser.parse_args(argv)
    output=args.output or Path(args.input.name+'.inspector.html')
    # Some native CAD importers write diagnostics straight to file descriptor 1.
    # Keep both the path-only protocol and the JSON protocol clean for callers.
    sys.stdout.flush()
    result_fd = os.dup(1)
    try:
        os.dup2(2, 1)
        try:
            result = build(args.input, output, title=args.title, grid=args.grid,
                           max_triangles=args.max_triangles, max_texture=args.max_texture,
                           renderer=args.renderer, runtime_source=args.runtime_source,
                           max_points=args.max_points)
        finally:
            sys.stdout.flush()
            os.dup2(result_fd, 1)
            os.close(result_fd)
    except MissingViewerDependency as exc:
        print(str(exc), file=sys.stderr)
        return exc.status
    except Exception as exc:
        print('Error:',str(exc),file=sys.stderr)
        return 1
    print(result['file'] if args.path_only else json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
