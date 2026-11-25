import bpy

from .lib import (
    activate_object,
    active_piece,
    apply_piece_edit,
    create_piece_mesh,
    create_sheet_material,
    direction_spin,
    delete_sheet,
    ensure_root_collection,
    find_sheet,
    grain_local_axes,
    mm_to_bu,
    move_piece_to_collection,
    piece_name,
    positive_dimensions,
    register_addon_class,
    sheet_materials,
    unregister_addon_class,
    store_piece_properties,
    store_sheet_properties,
    validate_sheet_name,
)
from .properties import remember_sheet_folders, sync_edit_from_active


class FC_OT_CreateSheet(bpy.types.Operator):
    bl_idname = "fc.create_sheet"
    bl_label = "Create Sheet"
    bl_description = "Create a collection and a material for a sheet"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.fc_sheet
        name, error = validate_sheet_name(props.sheet_name)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        if bpy.data.materials.get(name) is not None or bpy.data.collections.get(name) is not None:
            self.report({"ERROR"}, f"A material or collection named '{name}' already exists.")
            return {"CANCELLED"}

        error = positive_dimensions((
            ("Thickness", props.thickness_mm),
        ))
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        color = tuple(props.color)
        material = create_sheet_material(name, color, props.has_texture)
        if material.name != name:
            bpy.data.materials.remove(material)
            self.report({"ERROR"}, f"Could not create a material named '{name}'.")
            return {"CANCELLED"}

        root = ensure_root_collection(context.scene)
        collection = bpy.data.collections.new(name)
        root.children.link(collection)
        store_sheet_properties(
            material,
            collection,
            props.thickness_mm,
            props.has_texture,
            props.texture_direction,
            color,
        )

        try:
            context.scene.fc_piece.sheet_name = name
            context.scene.fc_sheet.selected_sheet = name
        except (TypeError, ValueError):
            pass
        remember_sheet_folders()

        self.report({"INFO"}, f"Created sheet {name}")
        return {"FINISHED"}


class FC_OT_CreatePiece(bpy.types.Operator):
    bl_idname = "fc.create_piece"
    bl_label = "Create Piece"
    bl_description = "Create a rectangular piece at the 3D cursor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.fc_piece
        material, collection = find_sheet(props.sheet_name)
        if material is None:
            self.report({"ERROR"}, "Select a sheet. Create one first if the list is empty.")
            return {"CANCELLED"}
        if collection is None:
            self.report({"ERROR"}, f"Collection '{material.name}' for this sheet is missing.")
            return {"CANCELLED"}

        error = positive_dimensions((
            ("Length", props.length_mm),
            ("Width", props.width_mm),
        ))
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        length = props.length_mm
        width = props.width_mm
        direction = props.direction
        thickness = float(material["fc_thickness_mm"])
        if thickness <= 0:
            self.report({"ERROR"}, f"Sheet '{material.name}' has no thickness.")
            return {"CANCELLED"}

        name = piece_name(direction, length, width, material.name)
        meters_per_bu = context.scene.unit_settings.scale_length
        texture_direction = None
        if material.get("fc_has_texture"):
            texture_direction = material.get("fc_texture_direction", "LENGTH")
        along, across = grain_local_axes(direction, texture_direction)

        mesh = create_piece_mesh(
            name,
            mm_to_bu(length, meters_per_bu),
            mm_to_bu(width, meters_per_bu),
            mm_to_bu(thickness, meters_per_bu),
            along,
            across,
            meters_per_bu,
        )
        obj = bpy.data.objects.new(name, mesh)
        obj.data.name = obj.name
        obj.location = context.scene.cursor.location
        obj.rotation_euler[2] = direction_spin(direction)
        obj.data.materials.append(material)
        store_piece_properties(obj, length, width, thickness, direction, material.name)
        collection.objects.link(obj)
        activate_object(context, obj)
        sync_edit_from_active()

        self.report({"INFO"}, f"Created {obj.name}")
        return {"FINISHED"}


class FC_OT_SavePiece(bpy.types.Operator):
    bl_idname = "fc.save_piece"
    bl_label = "Save Changes"
    bl_description = "Rename the selected piece and move it into its material collection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_piece(context) is not None

    def execute(self, context):
        obj = active_piece(context)
        if obj is None:
            self.report({"ERROR"}, "Select a piece.")
            return {"CANCELLED"}

        props = context.scene.fc_edit
        error = apply_piece_edit(
            obj,
            context.scene,
            props.length_mm,
            props.width_mm,
            props.direction,
            props.sheet_name,
        )
        if error:
            props.status = error
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        material, collection = find_sheet(props.sheet_name)
        if collection is None:
            message = f"Collection '{material.name}' for this sheet is missing."
            props.status = message
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        obj.name = piece_name(props.direction, props.length_mm, props.width_mm, material.name)
        obj.data.name = obj.name
        move_piece_to_collection(obj, collection)
        props.status = ""
        self.report({"INFO"}, f"Saved {obj.name}")
        return {"FINISHED"}


class FC_OT_DeleteSheet(bpy.types.Operator):
    bl_idname = "fc.delete_sheet"
    bl_label = "Delete Sheet"
    bl_description = "Delete the selected sheet, its folder, and the pieces inside that folder"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        material, _collection = find_sheet(context.scene.fc_sheet.selected_sheet)
        return material is not None

    def invoke(self, context, event):
        name = context.scene.fc_sheet.selected_sheet
        return context.window_manager.invoke_confirm(
            self,
            event,
            title="Delete Sheet",
            message=f"Delete {name}, its folder, and every piece inside?",
            confirm_text="Delete",
        )

    def execute(self, context):
        name = context.scene.fc_sheet.selected_sheet
        material, _collection = find_sheet(name)
        if material is None:
            self.report({"ERROR"}, "Select a sheet.")
            return {"CANCELLED"}
        delete_sheet(name)
        remember_sheet_folders()
        sync_edit_from_active()
        self.report({"INFO"}, f"Deleted sheet {name}")
        return {"FINISHED"}


classes = (
    FC_OT_CreateSheet,
    FC_OT_CreatePiece,
    FC_OT_SavePiece,
    FC_OT_DeleteSheet,
)


def register():
    for cls in classes:
        register_addon_class(cls)


def unregister():
    for cls in reversed(classes):
        unregister_addon_class(cls)
