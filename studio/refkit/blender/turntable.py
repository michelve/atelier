"""Blender (run with `blender -b -P turntable.py -- ...`): studio turntable or straight render of a .blend.

  --input      .glb/.gltf/.obj/.fbx/.blend
  --out        output folder (frames written as frames/####.png)
  --frames     turntable length (default 96 = 4 s at 24 fps); 1 = still
  --res        WxH (default 1600x1600; --as-is keeps the .blend's own unless given)
  --samples    Cycles samples (default 128, OptiX denoised; --as-is keeps the .blend's own unless given)
  --look       orbitra | neutral     (lighting + world preset; neutral = AgX base contrast + studio HDRI reflections)
  --as-is      for .blend input: render the file's own camera/animation/colour management instead of a turntable
  --transparent  transparent background (RGBA frames)
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--input", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--frames", type=int, default=96)
ap.add_argument("--res", default=None)
ap.add_argument("--samples", type=int, default=None)
ap.add_argument("--look", default="neutral", choices=["orbitra", "neutral"])
ap.add_argument("--as-is", action="store_true")
ap.add_argument("--transparent", action="store_true")
a = ap.parse_args(argv)


def hex_rgb(h, alpha=1.0):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return (*lin, alpha)


def use_gpu(scene):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = backend
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == backend]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == backend
                scene.cycles.device = "GPU"
                print(f"TURNTABLE device {backend}: {[d.name for d in gpus]}")
                return
        except TypeError:
            continue
    print("TURNTABLE device CPU (no OptiX/CUDA device found)")


def colour_management(scene, look):
    """neutral: AgX Base Contrast; orbitra: AgX Medium High Contrast.
    (Khronos PBR Neutral was tried for neutral on 2026-09-30: it pushed light ceramics yellow and the grey backdrop
    toward blue-black next to the source photo; AgX Base Contrast matched the photo.)"""
    scene.view_settings.view_transform = "AgX"
    wanted = ("AgX - Medium High Contrast", "Medium High Contrast") if look == "orbitra" else ("AgX - Base Contrast", "Base Contrast")
    for name in wanted:
        try:
            scene.view_settings.look = name
            break
        except TypeError:
            continue


def studio_hdri(world, strength):
    """Blender's bundled studio.exr as a soft reflection environment (metals read as metal, not flat grey)."""
    folder = bpy.utils.system_resource("DATAFILES", path="studiolights/world")
    path = os.path.join(folder or "", "studio.exr")
    if not os.path.isfile(path):
        return False
    nt = world.node_tree
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(path, check_existing=True)
    bg = nt.nodes.get("Background")
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = strength
    return True


def import_model(path):
    before = set(bpy.data.objects)
    ext = path.lower().rsplit(".", 1)[-1]
    if ext in ("glb", "gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == "obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == "fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        raise SystemExit(f"unsupported input: {path}")
    return [o for o in bpy.data.objects if o not in before]


def normalise(objs):
    """Group under an empty, centre on the origin with the base at z=0, largest side = 1 m."""
    meshes = [o for o in objs if o.type == "MESH"]
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    size = max(hi - lo)
    root = bpy.data.objects.new("refkit_root", None)
    bpy.context.scene.collection.objects.link(root)
    for o in objs:
        if o.parent is None:
            o.parent = root
    root.scale = [1 / size] * 3
    root.location = -Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)) / size
    for o in meshes:
        for poly in o.data.polygons:
            poly.use_smooth = True
    extent = (hi - lo) / size
    return extent.length / 2, extent.z / 2  # bounding-sphere radius, centre height


def area_light(name, loc, rot, size, size_y, energy, colour):
    data = bpy.data.lights.new(name, "AREA")
    data.shape = "RECTANGLE"
    data.size, data.size_y = size, size_y
    data.energy = energy
    data.color = hex_rgb(colour)[:3]
    obj = bpy.data.objects.new(name, data)
    obj.location, obj.rotation_euler = loc, [math.radians(r) for r in rot]
    bpy.context.scene.collection.objects.link(obj)
    return obj


def studio(scene, look):
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    if bpy.app.version < (5, 0, 0):  # always on since 5.0; the property goes away in 6.0
        world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if look == "orbitra":
        # ART_DIRECTION.md: near-black void, long thin cool-white grazing strips, low lavender rim, fill almost off.
        bg.inputs["Color"].default_value = hex_rgb("#0d0d12")
        bg.inputs["Strength"].default_value = 0.15
        area_light("strip_key", (2.2, -1.6, 1.6), (62, 0, 54), 3.2, 0.06, 260, "#f4f6ff")
        area_light("strip_top", (-0.4, 0.2, 2.4), (8, 0, 0), 2.6, 0.05, 160, "#eef0ff")
        area_light("rim_lavender", (-1.8, 2.0, 0.9), (70, 0, 218), 1.6, 0.4, 140, "#a79dff")
        area_light("fill", (-2.4, -2.2, 0.6), (80, 0, -48), 2.0, 2.0, 12, "#dcdcf0")
    else:
        bg.inputs["Color"].default_value = hex_rgb("#1a1a1f")
        bg.inputs["Strength"].default_value = 0.5
        studio_hdri(world, 0.35)   # reflections only; the area lights still shape the product
        # Camera sees a plain backdrop, not the HDRI photo.
        if not a.transparent:
            lp = world.node_tree.nodes.new("ShaderNodeLightPath")
            mix = world.node_tree.nodes.new("ShaderNodeMixShader")
            plain = world.node_tree.nodes.new("ShaderNodeBackground")
            plain.inputs["Color"].default_value = hex_rgb("#1a1a1f")
            out = world.node_tree.nodes.get("World Output")
            links = world.node_tree.links
            links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
            links.new(bg.outputs["Background"], mix.inputs[1])
            links.new(plain.outputs["Background"], mix.inputs[2])
            links.new(mix.outputs["Shader"], out.inputs["Surface"])
        area_light("key", (2.0, -2.0, 2.2), (50, 0, 45), 1.5, 1.5, 400, "#ffffff")
        area_light("fill", (-2.2, -1.5, 1.0), (70, 0, -55), 2.0, 2.0, 120, "#ffffff")
        area_light("rim", (0.0, 2.4, 1.6), (-60, 0, 0), 1.5, 0.3, 250, "#ffffff")


def turntable_camera(scene, frames, radius=0.87, centre_z=0.5, fill=0.82):
    """Distance chosen so the bounding sphere fills `fill` of the frame from any turntable angle."""
    pivot = bpy.data.objects.new("turntable_pivot", None)
    scene.collection.objects.link(pivot)
    cam_data = bpy.data.cameras.new("refkit_cam")
    cam_data.lens = 70
    cam_data.sensor_width = 36
    cam = bpy.data.objects.new("refkit_cam", cam_data)
    scene.collection.objects.link(cam)
    half_fov = math.atan(cam_data.sensor_width / 2 / cam_data.lens)
    dist, elev = radius / math.sin(half_fov) / fill, math.radians(16)
    cam.location = (0, -dist * math.cos(elev), centre_z + dist * math.sin(elev))
    track = cam.constraints.new("TRACK_TO")
    target = bpy.data.objects.new("cam_target", None)
    target.location = (0, 0, centre_z)
    scene.collection.objects.link(target)
    track.target = target
    cam.parent = pivot
    scene.camera = cam
    scene.frame_start, scene.frame_end = 1, frames
    if frames > 1:
        # Constant speed so the loop is seamless: frame N+1 == frame 1 and is never rendered.
        # (Set via preferences because Blender 5's layered actions no longer expose action.fcurves.)
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
        pivot.rotation_euler = (0, 0, 0)
        pivot.keyframe_insert("rotation_euler", index=2, frame=1)
        pivot.rotation_euler = (0, 0, math.radians(360))
        pivot.keyframe_insert("rotation_euler", index=2, frame=frames + 1)


scene = bpy.context.scene
if a.input.lower().endswith(".blend"):
    bpy.ops.wm.open_mainfile(filepath=a.input)
    scene = bpy.context.scene
    if not a.as_is:
        turntable_camera(scene, a.frames, *normalise([o for o in scene.objects if o.type == "MESH"]))
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    radius, centre_z = normalise(import_model(a.input))
    studio(scene, a.look)
    turntable_camera(scene, a.frames, radius, centre_z)

use_gpu(scene)
own_scene = a.as_is and a.input.lower().endswith(".blend")
if not own_scene:
    # --as-is keeps the .blend's own resolution, frame range, fps and colour management unless asked otherwise.
    colour_management(scene, a.look)
    scene.render.fps = 24
if a.res or not own_scene:
    w, h = (int(v) for v in (a.res or "1600x1600").lower().split("x"))
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = w, h, 100
if a.samples or not own_scene:
    scene.cycles.samples = a.samples or 128
scene.cycles.use_denoising = True
scene.render.use_persistent_data = True   # only the camera moves: keep BVH/textures between frames
scene.render.film_transparent = a.transparent or (own_scene and scene.render.film_transparent)
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA" if scene.render.film_transparent else "RGB"
scene.render.filepath = a.out.rstrip("/\\") + "/frames/"
bpy.ops.render.render(animation=True)
print("TURNTABLE-DONE", scene.frame_start, scene.frame_end)
