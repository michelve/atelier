"""Blender (run with `blender -b -P cleanup.py -- ...`): make a generated mesh production-ready.

  --input / --output   .glb in, .glb out
  --tris               target triangle count (decimate only if above; default 60000)
  --smooth-angle       auto-smooth angle in degrees (default 40)
  --material           keep | orbitra-metal | orbitra-glass   (replace materials with the house look)

Steps: join -> weld (merge by distance) -> drop loose geometry -> fill small holes -> decimate -> smooth by angle +
weighted normals -> centre with base at z=0, 1 m largest side -> apply transforms -> export glb.
With --keep-shading (textured meshes decimated before baking): no hole fill, decimate or re-shading.
"""
import argparse
import sys

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--input", required=True)
ap.add_argument("--output", required=True)
ap.add_argument("--tris", type=int, default=60000)
ap.add_argument("--smooth-angle", type=float, default=40)
ap.add_argument("--material", default="keep", choices=["keep", "orbitra-metal", "orbitra-glass"])
ap.add_argument("--keep-shading", action="store_true",
                help="textured mesh already at budget: no decimate/hole fill/re-shading (keeps UVs and the baked "
                     "tangent-space normal map valid; faces are shaded fully smooth, as the bake assumed)")
a = ap.parse_args(argv)


def hex_rgb(h):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return (*[c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb], 1.0)


def house_material(kind):
    m = bpy.data.materials.new(kind)
    if bpy.app.version < (5, 0, 0):  # always on since 5.0; the property goes away in 6.0
        m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    if kind == "orbitra-metal":  # satin-black metal
        p.inputs["Base Color"].default_value = hex_rgb("#0b0b10")
        p.inputs["Metallic"].default_value = 1.0
        p.inputs["Roughness"].default_value = 0.34
    else:  # frosted glass with a faint lavender tint
        p.inputs["Base Color"].default_value = hex_rgb("#ece8ff")
        p.inputs["Transmission Weight"].default_value = 1.0
        p.inputs["Roughness"].default_value = 0.28
        p.inputs["IOR"].default_value = 1.45
    return m


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=a.input)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("CLEANUP no mesh in input")

# Bake parent transforms, then join into one object.
for o in bpy.context.scene.objects:
    o.select_set(o in meshes)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
for o in [o for o in bpy.context.scene.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

before = len(obj.data.polygons)
bm = bmesh.new()
bm.from_mesh(obj.data)
size = max(obj.dimensions) or 1.0
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=size * 1e-4)
loose = [v for v in bm.verts if not v.link_faces]
bmesh.ops.delete(bm, geom=loose, context="VERTS")
# Tiny floating islands (generator noise): drop connected parts under 0.5% of the face count.
islands, seen = [], set()
for f in bm.faces:
    if f.index in seen:
        continue
    stack, part = [f], []
    seen.add(f.index)
    while stack:
        cur = stack.pop()
        part.append(cur)
        for e in cur.edges:
            for nb in e.link_faces:
                if nb.index not in seen:
                    seen.add(nb.index)
                    stack.append(nb)
    islands.append(part)
bm.faces.ensure_lookup_table()
tiny = [part for part in islands if len(part) < 0.005 * len(bm.faces)]
small = [f for part in tiny for f in part] if len(tiny) < len(islands) else []
if small:
    bmesh.ops.delete(bm, geom=small, context="FACES")
if not a.keep_shading:  # filled faces would have no UVs on a textured mesh
    bmesh.ops.holes_fill(bm, edges=bm.edges, sides=8)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.to_mesh(obj.data)
bm.free()

if a.keep_shading:
    # The texture/normal/AO bakes were made on this exact mesh with fully smooth normals.
    bpy.ops.object.shade_smooth()
else:
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris > a.tris:
        dec = obj.modifiers.new("decimate", "DECIMATE")
        dec.ratio = a.tris / tris
        dec.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=dec.name)
    # Soft, rounded read: smooth by angle, then weighted normals so flat faces stay flat and edges stay soft.
    bpy.ops.object.shade_smooth_by_angle(angle=a.smooth_angle * 3.14159265 / 180)
    wn = obj.modifiers.new("weighted_normals", "WEIGHTED_NORMAL")
    wn.keep_sharp = True
    bpy.ops.object.modifier_apply(modifier=wn.name)

# Base at z=0, centred, largest side 1 m.
lo = Vector([min(v.co[i] for v in obj.data.vertices) for i in range(3)])
hi = Vector([max(v.co[i] for v in obj.data.vertices) for i in range(3)])
scale = 1 / max(hi - lo)
obj.location = -Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)) * scale
obj.scale = (scale,) * 3
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

if a.material != "keep":
    obj.data.materials.clear()
    obj.data.materials.append(house_material(a.material))

bpy.ops.export_scene.gltf(filepath=a.output, export_format="GLB", use_selection=False, export_apply=True)
after = sum(len(p.vertices) - 2 for p in obj.data.polygons)
print(f"CLEANUP-DONE faces_in={before} tris_out={after} islands_removed={len(tiny) if small else 0}")
