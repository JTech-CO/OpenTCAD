"""Explicit, hash-bound transfer of supported SUPREM silicon/oxide meshes.

No remeshing, interpolated doping, inferred electrodes or coordinate scaling
other than um to cm. Contact IDs always refer to original 1-based STR points.
"""
from collections import defaultdict
import argparse
from pathlib import Path
import math

from .contract import digest, strict_json

CONTACTS = ("source", "drain", "body", "gate")
NAMES = ["silicon", "oxide", *CONTACTS, "interface"]
TOL = 1e-10

def orient(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])

def connected(edges):
    graph=defaultdict(set)
    for a,b in edges:graph[a].add(b);graph[b].add(a)
    if not graph:return False
    seen=set();todo=[next(iter(graph))]
    while todo:
        v=todo.pop()
        if v in seen:continue
        seen.add(v);todo.extend(graph[v]-seen)
    return len(seen)==len(graph)

def validate_planarity(points,edges):
    """Sweep bounding boxes to reject crossings, T-junctions and partial overlaps."""
    ordered=sorted((min(points[a][0],points[b][0]),max(points[a][0],points[b][0]),a,b) for a,b in edges)
    active=[]
    for xmin,xmax,a,b in ordered:
        active=[edge for edge in active if edge[1]>=xmin-TOL]
        p,q=points[a],points[b]
        for _,_,c,d in active:
            r,s=points[c],points[d]
            if max(p[1],q[1])+TOL<min(r[1],s[1]) or max(r[1],s[1])+TOL<min(p[1],q[1]):continue
            op,oq,orr,os=orient(p,q,r),orient(p,q,s),orient(r,s,p),orient(r,s,q)
            if op*oq<0 and orr*os<0 and min(abs(op),abs(oq),abs(orr),abs(os))>1e-16:
                raise ValueError("mesh-crossing-edges")
            for point,i,j,k in ((r,c,a,b),(s,d,a,b),(p,a,c,d),(q,b,c,d)):
                if i in (j,k):continue
                u,v=points[j],points[k]
                if abs(orient(u,v,point))<1e-16 and min(u[0],v[0])-TOL<=point[0]<=max(u[0],v[0])+TOL and min(u[1],v[1])-TOL<=point[1]<=max(u[1],v[1])+TOL:
                    raise ValueError("mesh-nonconforming-edge")
        active.append((xmin,xmax,a,b))

def topology(profile):
    raw=profile["meshSource"]
    points={i:(x,y) for i,x,y in raw["points"]}
    regions=dict(raw["regions"])
    if len(regions)!=2 or sorted(regions.values())!=[1,3]:
        raise ValueError("mesh-requires-one-silicon-one-oxide")
    region_names={i:"silicon" if m==3 else "oxide" for i,m in regions.items()}
    if len(set(points.values()))!=len(points):raise ValueError("mesh-duplicate-coordinate")
    cells={name:[] for name in ("silicon","oxide")}
    incidence=defaultdict(list);seen=set();areas={"silicon":0.,"oxide":0.}
    for identifier,reg,a,b,c in raw["triangles"]:
        ids=[a,b,c];key=tuple(sorted(ids))
        if key in seen:raise ValueError("mesh-duplicate-triangle")
        seen.add(key)
        area=orient(points[a],points[b],points[c])/2
        if abs(area)<1e-16:raise ValueError("mesh-degenerate-triangle")
        name=region_names[reg]
        cells[name].append(ids);areas[name]+=abs(area)
        for u,v,w in ((a,b,c),(b,c,a),(c,a,b)):
            incidence[tuple(sorted((u,v)))].append((name,w,identifier))
    if any(len(v)>2 for v in incidence.values()):raise ValueError("mesh-nonmanifold")
    if any(not v for v in cells.values()):raise ValueError("mesh-empty-region")
    for (a,b),owners in incidence.items():
        if len(owners)==2 and orient(points[a],points[b],points[owners[0][1]])*orient(points[a],points[b],points[owners[1][1]])>=0:
            raise ValueError("mesh-folded-triangles")
    validate_planarity(points,incidence)
    for name in cells:
        ids={i for owners in incidence.values() for n,_,i in owners if n==name}
        adjacency=[(owners[0][2],owners[1][2]) for owners in incidence.values() if len(owners)==2 and owners[0][0]==owners[1][0]==name]
        if len(ids)>1 and (not connected(adjacency) or set(v for e in adjacency for v in e)!=ids):
            raise ValueError("mesh-disconnected-region")
    interface=[list(edge) for edge,owners in incidence.items() if len(owners)==2 and owners[0][0]!=owners[1][0]]
    if not connected(interface):raise ValueError("mesh-interface-missing-or-disconnected")
    return points,region_names,cells,incidence,interface,areas

def prepare_mesh(profile,manifest):
    if not isinstance(manifest,dict) or set(manifest)!={"format","schemaVersion","sourceSha256","contacts"} or manifest["format"]!="opentcad-suprem-contacts" or type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"]!=1 or manifest["sourceSha256"]!=profile["sourceSha256"]:
        raise ValueError("contact-manifest-source")
    if not isinstance(manifest["contacts"],dict) or set(manifest["contacts"])!=set(CONTACTS):raise ValueError("contact-manifest-names")
    points,region_names,cells,incidence,interface,areas=topology(profile)
    doping=dict(profile["meshSource"]["siliconDoping"])
    contacts={};used=set();contact_nodes=set();interface_nodes={i for edge in interface for i in edge}
    for name in CONTACTS:
        value=manifest["contacts"][name]
        if not isinstance(value,dict) or set(value)!={"region","edges"} or type(value["region"]) is not int:raise ValueError("contact-shape")
        expected="oxide" if name=="gate" else "silicon"
        if region_names.get(value["region"])!=expected or not isinstance(value["edges"],list) or not 1<=len(value["edges"])<=2000:raise ValueError("contact-region")
        edges=[];vertices=set();degree=defaultdict(int)
        for edge in value["edges"]:
            if not isinstance(edge,list) or len(edge)!=2 or any(type(i) is not int for i in edge):raise ValueError("contact-edge")
            key=tuple(sorted(edge));owners=incidence.get(key,[])
            if key in used or len(owners)!=1 or owners[0][0]!=expected:raise ValueError("contact-not-exterior")
            used.add(key);edges.append(list(key));vertices.update(key)
            for i in key:degree[i]+=1
        if not connected(edges) or max(degree.values())>2 or sum(v==1 for v in degree.values())!=2:raise ValueError("contact-not-open-chain")
        if vertices&contact_nodes or vertices&interface_nodes:raise ValueError("contact-touching")
        contact_nodes.update(vertices)
        if name!="gate" and any((doping[i]>=0 if name=="body" else doping[i]<=0) for i in vertices):raise ValueError("contact-doping-polarity")
        contacts[name]=sorted(edges)
    # Reject a non-MOS all-n interface, while allowing n+ overlap at its ends.
    if not any(doping[i]<0 for i in interface_nodes):raise ValueError("mesh-channel-not-p-type")
    used_points=sorted({i for group in cells.values() for cell in group for i in cell})
    index={i:n for n,i in enumerate(used_points)}
    coordinates=[v for i in used_points for v in (*[x*1e-4 for x in points[i]],0.)]
    elements=[]
    for name,group in cells.items():
        for ids in group:elements.extend([2,NAMES.index(name),*[index[i] for i in ids]])
    for name,edges in {**contacts,"interface":interface}.items():
        for a,b in edges:elements.extend([1,NAMES.index(name),index[a],index[b]])
    source_doping={f"{points[i][0]:.17g},{points[i][1]:.17g}":v for i,v in doping.items() if i in index}
    result={"coordinates":coordinates,"elements":elements,"names":NAMES,"doping":source_doping,
            "contactSegmentsUm":{name:[[list(points[a]),list(points[b])] for a,b in edges] for name,edges in contacts.items()},
            "areasUm2":areas,"triangleCounts":{name:len(cells[name]) for name in cells},
            "sourceSha256":profile["sourceSha256"],"contactsSha256":digest(manifest)}
    result["meshSha256"]=digest(result)
    return result

def read_contacts(path):
    with Path(path).open("rb") as stream:return strict_json(stream.read(131073),maximum_bytes=131072)

def nodal_doping(mesh,x,y):
    # DEVSIM may reorder nodes, but must not move or insert them. Convert back
    # from cm and match within floating roundoff only, never interpolate.
    source=[(*map(float,key.split(",")),n) for key,n in mesh["doping"].items()]
    values=[]
    for px,py in zip(x,y):
        matches=[n for sx,sy,n in source if math.isclose(px*1e4,sx,rel_tol=1e-12,abs_tol=1e-13) and math.isclose(py*1e4,sy,rel_tol=1e-12,abs_tol=1e-13)]
        if len(matches)!=1:raise ValueError("mesh-node-transfer")
        values.append(matches[0])
    return values

def rectangular_manifest(profile,gate_length=1.,oxide_nm=10.):
    """Explicit helper for our rectangular deck only, not a general inference rule."""
    if type(gate_length) not in (int,float) or not .5<=gate_length<=2 or type(oxide_nm) not in (int,float) or not 5<=oxide_nm<=30:raise ValueError("recipe-geometry")
    points,names,_,incidence,_,_=topology(profile)
    ids={v:k for k,v in names.items()}
    length=gate_length+1
    contacts={name:{"region":ids["oxide" if name=="gate" else "silicon"],"edges":[]} for name in CONTACTS}
    def near(a,b):return abs(a-b)<1e-8
    for (a,b),owners in incidence.items():
        if len(owners)!=1:continue
        xy=[points[a],points[b]];region=owners[0][0]
        target=None
        if region=="silicon":
            if all(near(y,.5) for x,y in xy):target="body"
            elif all(near(y,0) and x<=.4+TOL for x,y in xy):target="source"
            elif all(near(y,0) and x>=length-.4-TOL for x,y in xy):target="drain"
        elif all(near(y,-oxide_nm*.001) and .5-TOL<=x<=length-.5+TOL for x,y in xy):target="gate"
        if target:contacts[target]["edges"].append([a,b])
    manifest={"format":"opentcad-suprem-contacts","schemaVersion":1,"sourceSha256":profile["sourceSha256"],"contacts":contacts}
    prepare_mesh(profile,manifest)
    return manifest

def main():
    from .suprem import read_structure
    from .contract import canonical
    parser=argparse.ArgumentParser(description="Generate contacts for the explicit rectangular SUPREM recipe; inspect before using")
    parser.add_argument("structure",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--gate-length",type=float,default=1.)
    parser.add_argument("--oxide-nm",type=float,default=10.)
    args=parser.parse_args()
    manifest=rectangular_manifest(read_structure(args.structure),args.gate_length,args.oxide_nm)
    with args.output.open("xb") as stream:stream.write(canonical(manifest))
    print("Validated explicit rectangular contacts; SHA-256:",digest(manifest))

if __name__=="__main__":main()
