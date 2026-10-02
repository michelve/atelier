"""Blender (run with `blender -b -P views.py -- ...`): QA views of a model + mesh facts, for `refkit inspect`.

  --input   .glb/.gltf/.obj/.fbx
  --out     folder: views/beauty_AAA.png, views/clay_AAA.png (AAA = azimuth in degrees) and stats.json
  --views   number of azimuths around the model (default 8, starting at the front)
  --azimuths  explicit list instead, e.g. "0,90,180,270"
  --elev    camera elevation in degrees (default 15)
  --fov     horizontal field of view in degrees (default 28.8 = a 70 mm lens); --fill = share of the frame
  --modes   beauty,clay (default both)
  --res     square size per view (default 640)
--rig     Pixal3D multi-view rig framing (used by `to3d --refine-views`): the model's bounding box scaled to a unit
          cube centred on the origin, camera on the orbit at 0.55 / tan(fov/2) looking at the centre, so the cube spans
          1/1.1 of the frame — the same scale in every view (Pixal3DMultiViewConditioning's contract).

beauty = Cycles (GPU, 32 samples, denoised) under Blender's bundled studio HDRI: textures, PBR, seams.
clay   = Workbench grey matcap with cavity: geometry only — holes, lumps, staircase/remesh artifacts, lost edges.
The model is shown as it is (its own normals and smoothing); it is only scaled to 1 m and centred.
"""
import argparse
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--input", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--views", type=int, default=8)
ap.add_argument("--azimuths", default=None)
ap.add_argument("--elev", type=float, default=15)
ap.add_argument("--fov", type=float, default=None)
ap.add_argument("--fill", type=float, default=0.9)
ap.add_argument("--modes", default="beauty,clay")
ap.add_argument("--rig", action="store_true")
ap.add_argument("--res", type=int, default=640)
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
ext = a.input.lower().rsplit(".", 1)[-1]
if ext in ("glb", "gltf"):
    bpy.ops.import_scene.gltf(filepath=a.input)
elif ext == "obj":
    bpy.ops.wm.obj_import(filepath=a.input)
elif ext == "fbx":
    bpy.ops.import_scene.fbx(filepath=a.input)
else:
    raise SystemExit(f"unsupported input: {a.input}")
meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh in the file")


def stats():
    """Facts the qa gates use: counts, UVs, materials/textures, open and non-manifold edges, degenerate faces."""
    s = {"objects": len(meshes), "verts": 0, "faces": 0, "tris": 0, "uv_layers": [], "boundary_edges": 0,
         "non_manifold_edges": 0, "degenerate_faces": 0, "materials": [], "textures": []}
    for o in meshes:
        me = o.data
        s["verts"] += len(me.vertices)
        s["faces"] += len(me.polygons)
        s["tris"] += sum(len(p.vertices) - 2 for p in me.polygons)
        s["uv_layers"] += [uv.name for uv in me.uv_layers]
        bm = bmesh.new()
        bm.from_mesh(me)
        # glTF import splits vertices along UV/normal seams; weld a copy so seams don't count as holes.
        size = max(o.dimensions) or 1.0
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=size * 1e-6)
        s["boundary_edges"] += sum(1 for e in bm.edges if e.is_boundary)
        s["non_manifold_edges"] += sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
        s["degenerate_faces"] += sum(1 for f in bm.faces if f.calc_area() < 1e-12)
        bm.free()
        for slot in o.material_slots:
            m = slot.material
            if not m or m.name in s["materials"]:
                continue
            s["materials"].append(m.name)
            for n in (m.node_tree.nodes if m.node_tree else []):
                if n.type == "TEX_IMAGE" and n.image:
                    links = [ln.to_socket.name for ln in m.node_tree.links if ln.from_node == n]
                    s["textures"].append({"image": n.image.name, "size": list(n.image.size), "feeds": links})
    return s


# Normalise: largest side 1 m, centred, base at z=0 (same convention as the turntable).
bpy.context.view_layer.update()
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
size = max(hi - lo)
root = bpy.data.objects.new("refkit_root", None)
scene.collection.objects.link(root)
for o in scene.objects:
    if o.parent is None and o is not root:
        o.parent = root
root.scale = [1 / size] * 3
if a.rig:   # unit cube centred on the origin
    root.location = -Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2)) / size
else:       # base at z = 0
    root.location = -Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)) / size
extent = (hi - lo) / size
radius, centre_z = extent.length / 2, (0.0 if a.rig else extent.z / 2)

cam_data = bpy.data.cameras.new("qa_cam")
cam_data.sensor_width = 36
cam_data.lens = 18 / math.tan(math.radians(a.fov) / 2) if a.fov else 70
cam = bpy.data.objects.new("qa_cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
target = bpy.data.objects.new("qa_target", None)
target.location = (0, 0, centre_z)
scene.collection.objects.link(target)
cam.constraints.new("TRACK_TO").target = target
dist = (0.55 / math.tan(math.atan(18 / cam_data.lens)) if a.rig
        else radius / math.sin(math.atan(18 / cam_data.lens)) / a.fill)
elev = math.radians(a.elev)

world = bpy.data.worlds.new("qa_world")
scene.world = world
nt = world.node_tree
bg = nt.nodes.get("Background")
hdri = os.path.join(bpy.utils.system_resource("DATAFILES", path="studiolights/world") or "", "studio.exr")
if os.path.isfile(hdri):
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(hdri, check_existing=True)
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 1.0

scene.render.resolution_x = scene.render.resolution_y = a.res
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "AgX"

prefs = bpy.context.preferences.addons["cycles"].preferences
for backend in ("OPTIX", "CUDA", "METAL", "HIP", "ONEAPI"):   # NVIDIA, Apple Silicon, AMD, Intel
    try:
        prefs.compute_device_type = backend
        prefs.get_devices()
        if any(d.type == backend for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == backend
            scene.cycles.device = "GPU"
            break
    except TypeError:
        continue
scene.cycles.samples = 32
scene.cycles.use_denoising = True
scene.render.use_persistent_data = True

views_dir = os.path.join(a.out, "views")
os.makedirs(views_dir, exist_ok=True)
azimuths = ([round(float(v)) for v in a.azimuths.split(",")] if a.azimuths
            else [round(i * 360 / a.views) for i in range(a.views)])


def place(az):
    # Azimuth 0 = the glTF front (+Y forward in glTF is -Y in Blender after import): camera on -Y looking +Y.
    t = math.radians(az)
    cam.location = (dist * math.sin(t) * math.cos(elev), -dist * math.cos(t) * math.cos(elev),
                    centre_z + dist * math.sin(elev))


for mode in [m.strip() for m in a.modes.split(",") if m.strip()]:
    if mode == "beauty":
        scene.render.engine = "CYCLES"
    else:
        scene.render.engine = "BLENDER_WORKBENCH"
        sh = scene.display.shading
        sh.light, sh.color_type = "MATCAP", "SINGLE"
        sh.single_color = (0.8, 0.8, 0.8)
        sh.show_cavity, sh.cavity_type = True, "BOTH"
    for az in azimuths:
        place(az)
        scene.render.filepath = os.path.join(views_dir, f"{mode}_{az:03d}.png")
        bpy.ops.render.render(write_still=True)

with open(os.path.join(a.out, "stats.json"), "w", encoding="utf-8") as f:
    json.dump({"input": a.input, "azimuths": azimuths, **stats()}, f, indent=2)
print("VIEWS-DONE", len(azimuths))
