"""Tessellate boundary-representation CAD locally and reuse the static mesh renderer."""
import math

import numpy as np
import trimesh
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESControl import IGESControl_Reader
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape


def shapes(path):
    if path.suffix.lower() == '.brep':
        shape = TopoDS_Shape()
        if not BRepTools.Read_s(shape, str(path), BRep_Builder()) or shape.IsNull():
            raise ValueError('Open CASCADE could not read this BREP file')
        return [shape]
    reader = STEPControl_Reader() if path.suffix.lower() in ('.stp', '.step') else IGESControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone or not reader.TransferRoots():
        raise ValueError('Open CASCADE could not transfer the CAD model')
    return [reader.Shape(i) for i in range(1, reader.NbShapes()+1)]


def parts(shape):
    solids = TopExp_Explorer(shape, TopAbs_SOLID)
    while solids.More():
        yield solids.Current()
        solids.Next()
    # Surface-only IGES models and shells in mixed compounds have no solid parent.
    faces = TopExp_Explorer(shape, TopAbs_FACE, TopAbs_SOLID)
    while faces.More():
        yield faces.Current()
        faces.Next()


def cad_scene(path):
    scene = trimesh.Scene()
    for shape in shapes(path):
        bounds = Bnd_Box()
        BRepBndLib.Add_s(shape, bounds)
        if bounds.IsVoid():
            continue
        box = bounds.Get()
        tolerance = max(1e-6, math.dist(box[:3], box[3:]) * .0005)
        mesher = BRepMesh_IncrementalMesh(shape, tolerance, False, .3, False)
        if not mesher.IsDone():
            raise ValueError('CAD tessellation did not complete')
        for part in parts(shape):
            vertices, triangles = [], []
            faces = TopExp_Explorer(part, TopAbs_FACE)
            while faces.More():
                face, location = TopoDS.Face_s(faces.Current()), TopLoc_Location()
                faces.Next()
                mesh = BRep_Tool.Triangulation_s(face, location)
                if mesh is None:
                    continue
                transform, first = location.Transformation(), len(vertices)-1
                for i in range(1, mesh.NbNodes()+1):
                    p = mesh.Node(i).Transformed(transform)
                    # Engineering CAD generally uses Z up; viewer space uses Y up.
                    vertices.append((p.X(), p.Z(), -p.Y()))
                for i in range(1, mesh.NbTriangles()+1):
                    a,b,c = mesh.Triangle(i).Get()
                    if face.Orientation() == TopAbs_REVERSED:
                        b,c = c,b
                    triangles.append((first+a, first+b, first+c))
            if triangles:
                label = f'Part {len(scene.geometry)+1}'
                scene.add_geometry(trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(triangles), process=False),
                                   node_name=label, geom_name=label)
    if not scene.geometry:
        raise ValueError('CAD file contains no tessellatable faces')
    return scene
