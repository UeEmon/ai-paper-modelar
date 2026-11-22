"""Small closed primitive components inferred from a photo; all dimensions estimated."""
from math import cos, sin, pi, radians
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field
from .mesh_unfolder import load_mesh


Dimension=Annotated[float,Field(ge=.5,le=200)]
Coordinate=Annotated[float,Field(ge=-300,le=300)]


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    shape: Literal["box", "cylinder", "cone", "gable_roof"]
    name: str = Field(default="part", max_length=60)
    position: tuple[Coordinate, Coordinate, Coordinate]  # bottom centre; y up
    size: tuple[Dimension, Dimension, Dimension]
    yaw: float = Field(default=0, ge=-180, le=180)
    top_ratio: float = Field(default=0, ge=0, le=1)
    sides: int = Field(default=6, ge=3, le=8)
    color: str = Field(default="#c9b38b", pattern=r"^#[0-9a-fA-F]{6}$")


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    components: list[Component] = Field(min_length=1, max_length=10)
    notes: list[str] = Field(default_factory=list, max_length=6)


def primitive(part):
    w, h, d = (v / 2 for v in part.size)
    if part.shape == "box":
        vertices = [(-w, 0, -d), (w, 0, -d), (w, 2*h, -d), (-w, 2*h, -d),
                    (-w, 0, d), (w, 0, d), (w, 2*h, d), (-w, 2*h, d)]
        polygons = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(3,7,6,2),(0,4,7,3),(1,2,6,5)]
    elif part.shape == "gable_roof":
        vertices = [(-w,0,-d),(w,0,-d),(0,2*h,-d),(-w,0,d),(w,0,d),(0,2*h,d)]
        polygons = [(0,2,1),(3,4,5),(0,1,4,3),(0,3,5,2),(1,2,5,4)]
    else:
        n=part.sides
        vertices=[(w*cos(2*pi*i/n),0,d*sin(2*pi*i/n)) for i in range(n)]
        ratio=1 if part.shape=="cylinder" else part.top_ratio
        polygons=[tuple(range(n))]
        if ratio==0:
            vertices.append((0,2*h,0))
            polygons += [(i,n,(i+1)%n) for i in range(n)]
        else:
            vertices += [(ratio*w*cos(2*pi*i/n),2*h,ratio*d*sin(2*pi*i/n)) for i in range(n)]
            polygons += [tuple(range(2*n-1,n-1,-1))]
            polygons += [(i,n+i,n+(i+1)%n,(i+1)%n) for i in range(n)]
    faces=[]
    for polygon in polygons:
        faces += [(polygon[0],polygon[i],polygon[i+1]) for i in range(1,len(polygon)-1)]
    # Separate closed components at contacts so the generic importer does not weld them.
    angle=radians(part.yaw)
    transformed=[]
    for x,y,z in vertices:
        x,y,z=x*.99,(y-h)*.99+h,z*.99
        transformed.append((x*cos(angle)+z*sin(angle)+part.position[0],
                            y+part.position[1],-x*sin(angle)+z*cos(angle)+part.position[2]))
    return transformed,faces


def build_model(scene: Scene, height_mm: float):
    vertices,faces,colors=[],[],[]
    for part in scene.components:
        if any(not .5<=v<=200 for v in part.size) or any(abs(v)>300 for v in part.position):
            raise ValueError("Component dimensions out of bounds")
        verts,tris=primitive(part);offset=len(vertices)
        vertices.extend(verts);faces.extend(tuple(i+offset for i in f) for f in tris)
        colors.extend([part.color]*len(tris))
    low=[min(v[i] for v in vertices) for i in range(3)]
    high=[max(v[i] for v in vertices) for i in range(3)]
    factor=height_mm/(high[1]-low[1]);centre=[(a+b)/2 for a,b in zip(low,high)]
    vertices=[((v[0]-centre[0])*factor,(v[1]-low[1])*factor,(v[2]-centre[2])*factor) for v in vertices]
    if any((b-a)*factor>1000 for a,b in zip(low,high)):
        raise ValueError("Model proportions too extreme")
    lines=["# AI inferred approximate model; units: mm; dimensions are estimates."]
    lines += ["v %.6f %.6f %.6f" % vertex for vertex in vertices]
    lines += ["f %d %d %d" % tuple(i+1 for i in face) for face in faces]
    obj="\n".join(lines)+"\n"
    load_mesh(obj.encode(),"image-model.obj")  # reject degenerate/non-manifold output
    return {"vertices":vertices,"faces":faces,"colors":colors,"obj":obj,
            "size_mm":[round((b-a)*factor,2) for a,b in zip(low,high)]}
