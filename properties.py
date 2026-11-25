import bpy
from bpy.app.handlers import persistent

from .lib import (
    active_piece,
    apply_piece_edit,
    delete_sheet,
    format_mm,
    register_addon_class,
    sheet_materials,
    unregister_addon_class,
)

_SUSPEND_EDIT_SYNC = False
_SYNCING_SELECTION = False
_LAST_ACTIVE_NAME = None
_MSG_OWNER = object()
_known_sheet_folders = None
_suspend_sheet_cleanup = False

DIRECTION_ITEMS = (
    (
        "ld",
        "ld  length → length",
        "Piece length runs along the sheet length (X)",
    ),
    (
        "lf",
        "lf  length → width",
        "Piece length runs along the sheet width (Y). Rotated 90°",
    ),
    (
        "n",
        "n  either way",
        "Placed with length along X, and marked as free to rotate",
    ),
)

_sheet_enum_items = []


def sheet_enum_items(self, context):
    _sheet_enum_items.clear()
    for material in sheet_materials():
        thickness = format_mm(material.get("fc_thickness_mm", 0))
        if material.get("fc_has_texture"):
            grain = "length" if material.get("fc_texture_direction") == "LENGTH" else "width"
            grain_text = f"grain along {grain}"
        else:
            grain_text = "no texture"
        description = f"{thickness} mm, {grain_text}"
        _sheet_enum_items.append((material.name, material.name, description))
    if not _sheet_enum_items:
        _sheet_enum_items.append(("NONE", "No sheets yet", "Create a sheet first"))
    return _sheet_enum_items


class FC_SheetProps(bpy.types.PropertyGroup):
    sheet_name: bpy.props.StringProperty(
        name="Name",
        description="Name of the collection and the material",
        default="DSP white",
    )
    thickness_mm: bpy.props.FloatProperty(
        name="Thickness",
        description="Sheet thickness in millimeters, along global Z. Pieces use this thickness",
        default=18.0,
        min=1.0,
        soft_max=60.0,
        step=10,
        precision=1,
    )
    has_texture: bpy.props.BoolProperty(
        name="Texture",
        description="Show wood grain on pieces cut from this sheet",
        default=True,
    )
    texture_direction: bpy.props.EnumProperty(
        name="Texture Direction",
        description="Which sheet axis the grain follows",
        items=(
            ("LENGTH", "Length", "Grain runs along the sheet length (X)"),
            ("WIDTH", "Width", "Grain runs along the sheet width (Y)"),
        ),
        default="LENGTH",
    )
    color: bpy.props.FloatVectorProperty(
        name="Color",
        description="Base color. With texture on, this tints the grain",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(0.9, 0.9, 0.88),
    )
    selected_sheet: bpy.props.EnumProperty(
        name="Sheet",
        description="Existing sheet. Delete removes this sheet, its folder, and its pieces",
        items=sheet_enum_items,
    )


class FC_PieceProps(bpy.types.PropertyGroup):
    length_mm: bpy.props.FloatProperty(
        name="Length",
        description="Piece length in millimeters. Local X of the piece",
        default=1200.0,
        min=1.0,
        soft_max=4000.0,
        step=100,
        precision=1,
    )
    width_mm: bpy.props.FloatProperty(
        name="Width",
        description="Piece width in millimeters. Local Y of the piece",
        default=450.0,
        min=1.0,
        soft_max=3000.0,
        step=100,
        precision=1,
    )
    sheet_name: bpy.props.EnumProperty(
        name="Material",
        description="Sheet this piece is cut from",
        items=sheet_enum_items,
    )
    direction: bpy.props.EnumProperty(
        name="Direction",
        description="How the piece length is oriented on the sheet",
        items=DIRECTION_ITEMS,
        default="ld",
    )


def update_edit_piece(self, context):
    global _SUSPEND_EDIT_SYNC
    if _SUSPEND_EDIT_SYNC or context is None:
        return
    obj = active_piece(context)
    if obj is None:
        return
    error = apply_piece_edit(
        obj,
        context.scene,
        self.length_mm,
        self.width_mm,
        self.direction,
        self.sheet_name,
    )
    if error:
        self.status = error
        sync_edit_from_active(clear_status=False)
        return
    self.status = ""


class FC_EditProps(bpy.types.PropertyGroup):
    length_mm: bpy.props.FloatProperty(
        name="Length",
        description="Piece length in millimeters. Updates the selected piece immediately",
        default=1200.0,
        min=1.0,
        soft_max=4000.0,
        step=100,
        precision=1,
        update=update_edit_piece,
    )
    width_mm: bpy.props.FloatProperty(
        name="Width",
        description="Piece width in millimeters. Updates the selected piece immediately",
        default=450.0,
        min=1.0,
        soft_max=3000.0,
        step=100,
        precision=1,
        update=update_edit_piece,
    )
    sheet_name: bpy.props.EnumProperty(
        name="Material",
        description="Sheet for the selected piece. Thickness and material update immediately",
        items=sheet_enum_items,
        update=update_edit_piece,
    )
    direction: bpy.props.EnumProperty(
        name="Direction",
        description="How the piece length is oriented on the sheet. Updates the piece immediately",
        items=DIRECTION_ITEMS,
        default="ld",
        update=update_edit_piece,
    )
    status: bpy.props.StringProperty(
        name="Status",
        description="Result of the last edit",
        default="",
    )


classes = (
    FC_SheetProps,
    FC_PieceProps,
    FC_EditProps,
)


def sync_edit_from_active(clear_status=True):
    """Copy the active piece into the Edit Piece fields without writing back to it."""
    global _SUSPEND_EDIT_SYNC, _LAST_ACTIVE_NAME
    context = bpy.context
    try:
        scene = context.scene
    except (AttributeError, RuntimeError):
        return
    if scene is None or not hasattr(scene, "fc_edit"):
        return

    props = scene.fc_edit
    obj = active_piece(context)
    _LAST_ACTIVE_NAME = obj.name if obj is not None else ""
    _SUSPEND_EDIT_SYNC = True
    try:
        if obj is None:
            if clear_status:
                props.status = ""
            return
        props.length_mm = float(obj.get("fc_length_mm", props.length_mm))
        props.width_mm = float(obj.get("fc_width_mm", props.width_mm))
        direction = obj.get("fc_direction", "ld")
        if direction in {"ld", "lf", "n"}:
            props.direction = direction
        sheet = obj.get("fc_sheet", "")
        try:
            props.sheet_name = sheet
        except (TypeError, ValueError):
            props.status = f"Sheet '{sheet}' is missing."
            return
        if clear_status:
            props.status = ""
    finally:
        _SUSPEND_EDIT_SYNC = False


def _notify_active_object():
    sync_edit_from_active()


def _current_sheet_folders():
    try:
        collections = bpy.data.collections
    except AttributeError:
        return {}
    folders = {}
    for collection in collections:
        if collection.get("fc_is_sheet"):
            folders[collection.session_uid] = collection.get("fc_material") or collection.name
    return folders


def _assign_sheet_enum(props, attr, target):
    try:
        setattr(props, attr, target)
    except (TypeError, ValueError):
        pass


def _ensure_selected_sheet():
    try:
        scene = bpy.context.scene
    except (AttributeError, RuntimeError):
        return
    if scene is None or not hasattr(scene, "fc_sheet"):
        return
    names = [material.name for material in sheet_materials()]
    if not names:
        return
    target = names[0]
    if scene.fc_sheet.selected_sheet not in names:
        _assign_sheet_enum(scene.fc_sheet, "selected_sheet", target)
    if scene.fc_piece.sheet_name not in names:
        _assign_sheet_enum(scene.fc_piece, "sheet_name", target)


def remember_sheet_folders():
    """Remember sheet folders so a later removal can delete the matching sheet."""
    global _known_sheet_folders
    _known_sheet_folders = _current_sheet_folders()
    _ensure_selected_sheet()


def _missing_sheet_folder():
    if _suspend_sheet_cleanup or _known_sheet_folders is None:
        return False
    current = {uid for uid in _current_sheet_folders()}
    return any(uid not in current for uid in _known_sheet_folders)


def cleanup_removed_sheets():
    """Delete sheets whose folders were removed outside the add-on."""
    global _known_sheet_folders
    if _suspend_sheet_cleanup or _known_sheet_folders is None:
        if not _suspend_sheet_cleanup:
            remember_sheet_folders()
        return None

    current = _current_sheet_folders()
    removed_names = []
    for uid, material_name in _known_sheet_folders.items():
        if uid not in current and material_name not in removed_names:
            removed_names.append(material_name)
    _known_sheet_folders = current
    if not removed_names:
        return None

    for material_name in removed_names:
        delete_sheet(material_name)
    remember_sheet_folders()
    try:
        scene = bpy.context.scene
        names = [material.name for material in sheet_materials()]
        target = names[0] if names else "NONE"
        if scene.fc_sheet.selected_sheet in removed_names:
            _assign_sheet_enum(scene.fc_sheet, "selected_sheet", target)
        if scene.fc_piece.sheet_name in removed_names:
            _assign_sheet_enum(scene.fc_piece, "sheet_name", target)
        sync_edit_from_active()
    except (AttributeError, RuntimeError):
        pass
    return None


def schedule_sheet_cleanup():
    if bpy.app.timers.is_registered(cleanup_removed_sheets):
        return
    bpy.app.timers.register(cleanup_removed_sheets, first_interval=0.01)


@persistent
def on_depsgraph(_scene, _depsgraph):
    """Reload Edit Piece when the selection changes, and watch for deleted folders."""
    global _SYNCING_SELECTION
    if _missing_sheet_folder():
        schedule_sheet_cleanup()
    if _SYNCING_SELECTION or _SUSPEND_EDIT_SYNC:
        return
    try:
        obj = active_piece(bpy.context)
    except (AttributeError, RuntimeError):
        return
    name = obj.name if obj is not None else ""
    if name == _LAST_ACTIVE_NAME:
        return
    _SYNCING_SELECTION = True
    try:
        sync_edit_from_active()
    finally:
        _SYNCING_SELECTION = False


def subscribe_active_object():
    bpy.msgbus.clear_by_owner(_MSG_OWNER)
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.LayerObjects, "active"),
        owner=_MSG_OWNER,
        args=(),
        notify=_notify_active_object,
    )


def unsubscribe_active_object():
    bpy.msgbus.clear_by_owner(_MSG_OWNER)


@persistent
def on_load_pre(_dummy):
    global _known_sheet_folders, _suspend_sheet_cleanup
    _suspend_sheet_cleanup = True
    _known_sheet_folders = None


@persistent
def on_file_load(_dummy):
    global _suspend_sheet_cleanup
    _suspend_sheet_cleanup = False
    remember_sheet_folders()
    subscribe_active_object()
    sync_edit_from_active()


@persistent
def on_undo(_dummy):
    remember_sheet_folders()
    sync_edit_from_active()


def _finish_enable():
    remember_sheet_folders()
    sync_edit_from_active()
    return None


def _remove_scene_props():
    for name in ("fc_edit", "fc_piece", "fc_sheet"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


def register():
    _remove_scene_props()
    for cls in classes:
        register_addon_class(cls)
    bpy.types.Scene.fc_sheet = bpy.props.PointerProperty(type=FC_SheetProps)
    bpy.types.Scene.fc_piece = bpy.props.PointerProperty(type=FC_PieceProps)
    bpy.types.Scene.fc_edit = bpy.props.PointerProperty(type=FC_EditProps)
    subscribe_active_object()
    if on_load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(on_load_pre)
    if on_file_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_file_load)
    if on_undo not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(on_undo)
    if on_undo not in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.append(on_undo)
    if on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(on_depsgraph)
    # Enabling an add-on runs register() while bpy.data is blocked.
    try:
        bpy.data.collections
    except AttributeError:
        if not bpy.app.timers.is_registered(_finish_enable):
            bpy.app.timers.register(_finish_enable, first_interval=0.0)
    else:
        _finish_enable()


def unregister():
    unsubscribe_active_object()
    if on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(on_load_pre)
    if on_file_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_file_load)
    if on_undo in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(on_undo)
    if on_undo in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.remove(on_undo)
    if on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph)
    _remove_scene_props()
    for cls in reversed(classes):
        unregister_addon_class(cls)
