"""Fail-closed SUPREM-IV.GS 2D active-dopant transfer, not a general STR viewer.

ASCII STR contract: c coordinates are 1-based micrometres, n point references
are 0-based and material-specific; r maps region to material. Species codes
20/21/22 are active donors and 23 active boron. Code 24 is NOT trusted.
Only the documented B.9305 silicon/oxide/poly subset is accepted.
"""
import argparse
import hashlib
import math
from pathlib import Path

KNOWN_SPECIES = {0,1,2,3,4,5,8,9,12,14,19,20,21,22,23,24}
MAX_BYTES = 1_048_576

def parse_structure(source):
    if len(source)>MAX_BYTES: raise ValueError("str-size")
    text = source.decode("ascii")
    coords, regions, triangles, records = {}, {}, {}, {}
    species = None
    version = dimension = False
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"): continue
        kind, f = parts[0], parts[1:]
        if kind=="v":
            if version or f != ["SUPREM-IV.GS","B.9305"]: raise ValueError("str-version")
            version = True
        elif kind=="D":
            if dimension or f != ["2","3","3"]: raise ValueError("str-dimension")
            dimension = True
        elif kind=="c":
            if len(f)!=4: raise ValueError("str-coordinate")
            key = int(f[0]); xy = [float(f[1]),float(f[2])]
            if key<1 or key in coords or not all(math.isfinite(v) and abs(v)<=100 for v in xy): raise ValueError("str-coordinate")
            coords[key] = xy
        elif kind=="r":
            if len(f)!=2: raise ValueError("str-region")
            key, material = map(int,f)
            if key<1 or key in regions or material not in (1,3,4): raise ValueError("str-material")
            regions[key] = material
        elif kind=="t":
            if len(f)!=10: raise ValueError("str-triangle")
            v = list(map(int,f))
            if v[0]<1 or v[0] in triangles: raise ValueError("str-triangle-id")
            triangles[v[0]] = (v[1],v[2:5])
        elif kind=="s":
            if species is not None: raise ValueError("str-species-duplicate")
            species = list(map(int,f[1:]))
            if not f or int(f[0])!=len(species) or len(species)!=len(set(species)) or not set(species)<=KNOWN_SPECIES:
                raise ValueError("str-species")
            for chemical, active in ((2,20),(3,21),(4,22),(5,23)):
                if chemical in species and active not in species: raise ValueError("str-active-missing")
            if 23 not in species or not set(species)&{20,21,22}: raise ValueError("str-mos-dopants")
        elif kind=="n":
            if species is None or len(f)!=len(species)+2: raise ValueError("str-node-columns")
            point, material = int(f[0])+1,int(f[1])
            values = list(map(float,f[2:])); key=(point,material)
            if key in records or not all(math.isfinite(v) for v in values): raise ValueError("str-node")
            mapped = dict(zip(species,values))
            active = [mapped.get(s,0) for s in (20,21,22,23)]
            if any(v<0 or v>1e20 for v in active): raise ValueError("str-concentration")
            records[key] = sum(active[:3])-active[3]
        elif kind not in {"M","I"}:
            raise ValueError("str-unsupported-record")
    if not version or not dimension or not coords or not regions or not triangles or species is None:
        raise ValueError("str-incomplete")
    if len(coords)>4000 or len(triangles)>8000: raise ValueError("str-mesh-limit")
    cells, seen = [], set()
    for reg, ids in triangles.values():
        if reg not in regions or len(set(ids))!=3 or any(i not in coords for i in ids): raise ValueError("str-connectivity")
        if regions[reg]!=3: continue
        key = tuple(sorted(ids))
        if key in seen: raise ValueError("str-duplicate-cell")
        seen.add(key)
        if any((i,3) not in records for i in ids): raise ValueError("str-missing-silicon-data")
        xy = [coords[i] for i in ids]
        a,b,c = xy
        area = (b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1])
        if abs(area)<1e-16: raise ValueError("str-degenerate-cell")
        cells.append({"xy":xy,"doping":[records[i,3] for i in ids]})
    if not cells: raise ValueError("str-no-silicon")
    return {"sourceSha256":hashlib.sha256(source).hexdigest(),"cells":cells,
            "meshSource":{"points":[[i,*xy] for i,xy in sorted(coords.items())],
                          "regions":[[i,m] for i,m in sorted(regions.items())],
                          "triangles":[[i,reg,*ids] for i,(reg,ids) in sorted(triangles.items())],
                          "siliconDoping":[[i,n] for (i,m),n in sorted(records.items()) if m==3]}}

def read_structure(path):
    with Path(path).open("rb") as stream:
        return parse_structure(stream.read(MAX_BYTES+1))

def interpolate_profile(profile, points):
    """Linear barycentric interpolation in concentration units, no extrapolation.

    Reject overlaps with inconsistent values. Si/oxide boundary data remain
    material-specific. The full requested silicon mesh must be covered.
    """
    result = []
    for x,y in points:
        matches = []
        for cell in profile["cells"]:
            a,b,c = cell["xy"]
            if x<min(a[0],b[0],c[0])-1e-10 or x>max(a[0],b[0],c[0])+1e-10 or y<min(a[1],b[1],c[1])-1e-10 or y>max(a[1],b[1],c[1])+1e-10: continue
            det=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            u=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/det
            v=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/det
            w=1-u-v
            if min(u,v,w)<-1e-9: continue
            matches.append(sum(weight*n for weight,n in zip((u,v,w),cell["doping"])))
        if not matches: raise ValueError("str-template-not-covered")
        if any(not math.isclose(matches[0],v,rel_tol=1e-7,abs_tol=1e5) for v in matches): raise ValueError("str-overlap-conflict")
        result.append(matches[0])
    return result

def main():
    parser = argparse.ArgumentParser(description="Validate an external SUPREM 2D STR before local MOS coupling")
    parser.add_argument("structure",type=Path)
    args=parser.parse_args()
    profile=read_structure(args.structure)
    print(f'Silicon triangles: {len(profile["cells"])}; SHA-256: {profile["sourceSha256"]}')

if __name__=="__main__": main()
