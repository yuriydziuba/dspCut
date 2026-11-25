"""Sheet and piece data for Furniture Cut.

Sheet axes: length is global X, width is global Y, thickness is global Z.
A piece keeps local X as its length and local Y as its width.
ld leaves that aligned with the sheet. lf rotates +90° around Z, so the
piece length runs along the sheet width. n uses the ld placement and is
marked as free to rotate either way when cutting.

Grain, when the sheet has a texture, follows the sheet axis chosen as the
texture direction. Piece UVs are written so U runs along that grain. The
shared material always reads grain from U, which lets one material show a
different grain direction on ld and lf pieces.

Sheet material ID properties:
    fc_is_sheet, fc_length_mm, fc_width_mm, fc_thickness_mm,
    fc_has_texture, fc_texture_direction ('LENGTH' or 'WIDTH'), fc_color

Piece object ID properties:
    fc_is_piece, fc_length_mm, fc_width_mm, fc_thickness_mm,
    fc_direction ('ld', 'lf', or 'n'), fc_sheet
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT_COLLECTION = "Furniture Cut"
MAX_SHEET_NAME = 40
_FIT_EPSILON_MM = 0.001


def _classes_named(name):
    """Registered and unregistered classes that use this name.

    A second install loads another copy of the same class names. Those copies
    are not always visible on bpy.types, so look through the live subclasses.
    """
    found = []
    bases = (bpy.types.PropertyGroup, bpy.types.Operator, bpy.types.Panel)
    for base in bases:
        for subclass in base.__subclasses__():
            if subclass.__name__ == name and subclass not in found:
                found.append(subclass)
    return found


def register_addon_class(cls):
    """Register a class, replacing one already registered under the same name."""
    for existing in _classes_named(cls.__name__):
        if getattr(existing, "is_registered", False):
            try:
                bpy.utils.unregister_class(existing)
            except RuntimeError:
                pass
    bpy.utils.register_class(cls)


def unregister_addon_class(cls):
    for existing in _classes_named(cls.__name__):
        if not getattr(existing, "is_registered", False):
            continue
        try:
            bpy.utils.unregister_class(existing)
        except RuntimeError:
            pass


def format_mm(value):
    value = float(value)
    rounded = round(value)
    if abs(value - rounded) < 1e-6:
        return str(int(rounded))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def mm_to_bu(mm, meters_per_bu):
    scale = meters_per_bu if meters_per_bu else 1.0
    return (float(mm) / 1000.0) / scale


def _fits_length_along_sheet_length(length, width, sheet_length, sheet_width):
    return (
        length <= sheet_length + _FIT_EPSILON_MM
        and width <= sheet_width + _FIT_EPSILON_MM
    )


def _fits_length_along_sheet_width(length, width, sheet_length, sheet_width):
    return (
        length <= sheet_width + _FIT_EPSILON_MM
        and width <= sheet_length + _FIT_EPSILON_MM
    )


def piece_fits(length, width, sheet_length, sheet_width, direction):
    along_length = _fits_length_along_sheet_length(
        length, width, sheet_length, sheet_width
    )
    along_width = _fits_length_along_sheet_width(
        length, width, sheet_length, sheet_width
    )
    if direction == "ld":
        return along_length
    if direction == "lf":
        return along_width
    if direction == "n":
        return along_length or along_width
    return False


def fit_error_message(length, width, sheet_name, sheet_length, sheet_width, direction):
    piece = f"{format_mm(length)}×{format_mm(width)} mm"
    sheet = (
        f"{sheet_name} ({format_mm(sheet_length)}×{format_mm(sheet_width)} mm)"
    )
    if direction == "n":
        return f"Piece {piece} does not fit on {sheet} in either direction."
    if direction == "ld":
        need = (
            f"it needs {format_mm(length)} mm of sheet length "
            f"and {format_mm(width)} mm of sheet width"
        )
    else:
        need = (
            f"it needs {format_mm(length)} mm of sheet width "
            f"and {format_mm(width)} mm of sheet length"
        )
    return f"Piece {piece} does not fit on {sheet} in direction {direction}: {need}."


def grain_local_axes(direction, texture_direction):
    """Return local XY unit vectors (along grain, across grain).

    UVs use these so U follows the sheet grain after the piece rotation.
    Without a texture direction, U follows the piece length.
    """
    if texture_direction not in {"LENGTH", "WIDTH"}:
        return (1.0, 0.0), (0.0, 1.0)

    if direction == "lf":
        # +90° around Z: local +X → world +Y, local +Y → world -X.
        length_axis = (0.0, -1.0)
        width_axis = (1.0, 0.0)
    else:
        length_axis = (1.0, 0.0)
        width_axis = (0.0, 1.0)

    along = width_axis if texture_direction == "WIDTH" else length_axis
    across = (-along[1], along[0])
    return along, across


def validate_sheet_name(name):
    cleaned = (name or "").strip().rstrip(".")
    if not cleaned:
        return None, "Sheet name is empty."
    if len(cleaned) > MAX_SHEET_NAME:
        return None, f"Sheet name must be {MAX_SHEET_NAME} characters or fewer."
    if cleaned == ROOT_COLLECTION:
        return None, f"'{ROOT_COLLECTION}' is reserved for the root collection."
    return cleaned, None


def positive_dimensions(pairs):
    for label, value in pairs:
        if not math.isfinite(value) or value <= 0:
            return f"{label} must be greater than zero."
    return None


def _tag(id_block, key, description):
    id_block[key] = id_block[key]
    try:
        id_block.id_properties_ui(key).update(description=description)
    except (TypeError, AttributeError):
        pass


def ensure_root_collection(scene):
    root = bpy.data.collections.get(ROOT_COLLECTION)
    if root is None:
        root = bpy.data.collections.new(ROOT_COLLECTION)
    if root.name not in scene.collection.children:
        scene.collection.children.link(root)
    return root


def _tint(color, other, amount):
    return tuple(
        min(1.0, max(0.0, color[channel] * (1.0 - amount) + other[channel] * amount))
        for channel in range(3)
    )


def create_sheet_material(name, color, has_texture):
    """Material whose U axis is the grain direction. Pieces encode that in UVs."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = (color[0], color[1], color[2], 1.0)
    material.use_fake_user = True

    tree = material.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (420, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (140, 0)
    bsdf.inputs["Roughness"].default_value = 0.46 if has_texture else 0.55
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    if not has_texture:
        bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
        return material

    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-760, 80)
    wave = nodes.new("ShaderNodeTexWave")
    wave.location = (-480, 40)
    wave.wave_type = "BANDS"
    wave.bands_direction = "Y"
    # UV is in meters. Scale 6 is about 19 grain lines per meter.
    wave.inputs["Scale"].default_value = 6.0
    wave.inputs["Distortion"].default_value = 2.5
    wave.inputs["Detail"].default_value = 2.0
    wave.inputs["Detail Scale"].default_value = 0.8
    wave.inputs["Detail Roughness"].default_value = 0.4
    links.new(tex_coord.outputs["UV"], wave.inputs["Vector"])

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-180, 40)
    dark = _tint(color, (0.02, 0.015, 0.01), 0.78)
    light = _tint(color, (1.0, 1.0, 1.0), 0.18)
    stops = ramp.color_ramp.elements
    stops[0].position = 0.0
    stops[0].color = (*dark, 1.0)
    stops[1].position = 0.38
    stops[1].color = (color[0], color[1], color[2], 1.0)
    highlight = stops.new(0.78)
    highlight.color = (*light, 1.0)
    links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (-180, -220)
    bump.inputs["Strength"].default_value = 0.08
    links.new(wave.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return material


def store_sheet_properties(material, collection, length, width, thickness, has_texture, texture_direction, color):
    material["fc_is_sheet"] = True
    material["fc_length_mm"] = float(length)
    material["fc_width_mm"] = float(width)
    material["fc_thickness_mm"] = float(thickness)
    material["fc_has_texture"] = bool(has_texture)
    material["fc_texture_direction"] = texture_direction if has_texture else "LENGTH"
    material["fc_color"] = [float(color[0]), float(color[1]), float(color[2])]
    _tag(material, "fc_is_sheet", "Sheet material created by Furniture Cut")
    _tag(material, "fc_length_mm", "Sheet length, millimeters, global X")
    _tag(material, "fc_width_mm", "Sheet width, millimeters, global Y")
    _tag(material, "fc_thickness_mm", "Sheet thickness, millimeters, global Z")
    _tag(material, "fc_has_texture", "Sheet shows wood grain")
    _tag(material, "fc_texture_direction", "LENGTH or WIDTH, the sheet axis the grain follows")

    collection["fc_is_sheet"] = True
    collection["fc_material"] = material.name
    _tag(collection, "fc_is_sheet", "Sheet collection created by Furniture Cut")
    _tag(collection, "fc_material", "Material that owns this sheet")


def sheet_materials():
    try:
        materials = bpy.data.materials
    except AttributeError:
        return []
    return [mat for mat in materials if mat.get("fc_is_sheet")]


def find_sheet_collection(material_name):
    """Folder for a sheet, including after the collection has been renamed."""
    for collection in bpy.data.collections:
        if not collection.get("fc_is_sheet"):
            continue
        if collection.get("fc_material") == material_name or collection.name == material_name:
            return collection
    return None


def find_sheet(name):
    material = bpy.data.materials.get(name)
    if material is None or not material.get("fc_is_sheet"):
        return None, None
    return material, find_sheet_collection(material.name)


def _parent_collection(collection, parent=None):
    if parent is None:
        parent = bpy.context.scene.collection
    for child in parent.children:
        if child == collection:
            return parent
        found = _parent_collection(collection, child)
        if found is not None:
            return found
    return None


def _remove_object(obj):
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def delete_sheet(name):
    """Delete the sheet material, its folder, and the pieces that belong to it.

    Other objects that were only stored in the folder are moved to the parent
    collection so they are not lost with the folder.
    """
    _material, collection = find_sheet(name)
    if collection is None:
        collection = find_sheet_collection(name)

    for obj in list(bpy.data.objects):
        if not obj.get("fc_is_piece"):
            continue
        in_folder = collection is not None and any(
            coll == collection for coll in obj.users_collection
        )
        if obj.get("fc_sheet") == name or in_folder:
            _remove_object(obj)

    if collection is not None:
        holder = _parent_collection(collection)
        if holder is None:
            holder = bpy.context.scene.collection
        for obj in list(collection.objects):
            if obj.name not in holder.objects:
                try:
                    holder.objects.link(obj)
                except RuntimeError:
                    pass
        bpy.data.collections.remove(collection)

    material = bpy.data.materials.get(name)
    if material is not None and material.get("fc_is_sheet"):
        material.use_fake_user = False
        bpy.data.materials.remove(material)


def piece_name(direction, length, width, material_name):
    return f"{direction}_{format_mm(length)}x{format_mm(width)}_{material_name}"


def direction_spin(direction):
    """World Z rotation used when a piece is first created."""
    return math.pi / 2.0 if direction == "lf" else 0.0


def active_piece(context):
    if context is None:
        return None
    view_layer = getattr(context, "view_layer", None)
    if view_layer is None:
        return None
    obj = view_layer.objects.active
    if obj is not None and obj.get("fc_is_piece"):
        return obj
    return None


def _build_piece_bmesh(size_x, size_y, size_z, along, across, meters_per_bu):
    bm = bmesh.new()
    bmesh.ops.create_cube(
        bm,
        size=1.0,
        matrix=Matrix.Diagonal((size_x, size_y, size_z, 1.0)),
    )
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    scale = meters_per_bu if meters_per_bu else 1.0

    for face in bm.faces:
        top = abs(face.normal.z) > 0.5
        for loop in face.loops:
            co = loop.vert.co
            grain_u = (co.x * along[0] + co.y * along[1]) * scale
            if top:
                grain_v = (co.x * across[0] + co.y * across[1]) * scale
            else:
                grain_v = co.z * scale
            loop[uv_layer].uv = (grain_u, grain_v)
    return bm


def create_piece_mesh(name, size_x, size_y, size_z, along, across, meters_per_bu):
    mesh = bpy.data.meshes.new(name)
    bm = _build_piece_bmesh(size_x, size_y, size_z, along, across, meters_per_bu)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def _assign_mesh_material(mesh, material):
    mesh.materials.clear()
    mesh.materials.append(material)


def normalize_piece_scale(obj):
    scale = obj.matrix_world.to_scale()
    if (
        abs(scale.x - 1.0) < 1e-6
        and abs(scale.y - 1.0) < 1e-6
        and abs(scale.z - 1.0) < 1e-6
    ):
        return
    location, rotation, _scale = obj.matrix_world.decompose()
    obj.matrix_world = Matrix.LocRotScale(location, rotation, Vector((1.0, 1.0, 1.0)))


def spin_in_place_world_z(obj, delta):
    if abs(delta) < 1e-8:
        return
    pivot = obj.matrix_world.translation.copy()
    rotation = Matrix.Rotation(delta, 4, "Z")
    obj.matrix_world = (
        Matrix.Translation(pivot)
        @ rotation
        @ Matrix.Translation(-pivot)
        @ obj.matrix_world
    )


def apply_piece_edit(obj, scene, length, width, direction, sheet_name):
    """Update mesh, material, grain, and rotation. The name and collection stay put."""
    material, _collection = find_sheet(sheet_name)
    if material is None:
        return "Select a sheet."
    error = positive_dimensions((("Length", length), ("Width", width)))
    if error:
        return error
    if direction not in {"ld", "lf", "n"}:
        return "Unknown direction."

    sheet_length = float(material["fc_length_mm"])
    sheet_width = float(material["fc_width_mm"])
    thickness = float(material["fc_thickness_mm"])
    if thickness <= 0:
        return f"Sheet '{material.name}' has no thickness."
    if not piece_fits(length, width, sheet_length, sheet_width, direction):
        return fit_error_message(
            length, width, material.name, sheet_length, sheet_width, direction
        )

    old_direction = obj.get("fc_direction", "ld")
    view_layer = bpy.context.view_layer if bpy.context else None
    if view_layer is not None:
        view_layer.update()
    texture_direction = None
    if material.get("fc_has_texture"):
        texture_direction = material.get("fc_texture_direction", "LENGTH")
    along, across = grain_local_axes(direction, texture_direction)
    meters_per_bu = scene.unit_settings.scale_length

    normalize_piece_scale(obj)
    bm = _build_piece_bmesh(
        mm_to_bu(length, meters_per_bu),
        mm_to_bu(width, meters_per_bu),
        mm_to_bu(thickness, meters_per_bu),
        along,
        across,
        meters_per_bu,
    )
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    _assign_mesh_material(obj.data, material)
    store_piece_properties(obj, length, width, thickness, direction, material.name)
    spin_in_place_world_z(obj, direction_spin(direction) - direction_spin(old_direction))
    return None


def move_piece_to_collection(obj, collection):
    current = list(obj.users_collection)
    if current == [collection]:
        return
    for col in current:
        col.objects.unlink(obj)
    collection.objects.link(obj)


def store_piece_properties(obj, length, width, thickness, direction, sheet_name):
    obj["fc_is_piece"] = True
    obj["fc_length_mm"] = float(length)
    obj["fc_width_mm"] = float(width)
    obj["fc_thickness_mm"] = float(thickness)
    obj["fc_direction"] = direction
    obj["fc_sheet"] = sheet_name
    _tag(obj, "fc_is_piece", "Piece created by Furniture Cut")
    _tag(obj, "fc_length_mm", "Piece length, millimeters, local X")
    _tag(obj, "fc_width_mm", "Piece width, millimeters, local Y")
    _tag(obj, "fc_thickness_mm", "Piece thickness, millimeters, from the sheet")
    _tag(obj, "fc_direction", "ld, lf, or n")
    _tag(obj, "fc_sheet", "Sheet material this piece was cut from")


def activate_object(context, obj):
    view_layer = context.view_layer
    if obj.name not in view_layer.objects:
        view_layer.update()
    if obj.name not in view_layer.objects:
        return
    for other in view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj
