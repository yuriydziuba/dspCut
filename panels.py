import bpy

from .lib import (
    active_piece,
    find_sheet,
    format_mm,
    piece_fits,
    piece_name,
    register_addon_class,
    unregister_addon_class,
)


class FC_PT_Sheet(bpy.types.Panel):
    bl_label = "Sheet"
    bl_idname = "FC_PT_sheet"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Furniture Cut"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        props = context.scene.fc_sheet
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(props, "sheet_name")
        layout.prop(props, "length_mm", text="Length (mm)")
        layout.prop(props, "width_mm", text="Width (mm)")
        layout.prop(props, "thickness_mm", text="Thickness (mm)")
        layout.prop(props, "has_texture")
        if props.has_texture:
            layout.prop(props, "texture_direction", expand=True)
        layout.prop(props, "color")

        layout.use_property_split = False
        if props.has_texture:
            layout.label(text="Grain is visible in Material Preview", icon="SHADING_TEXTURE")
        layout.separator()
        layout.operator("fc.create_sheet", icon="MATERIAL")

        layout.separator()
        layout.label(text="Sheets")
        row = layout.row(align=True)
        row.prop(props, "selected_sheet", text="")
        row.operator("fc.delete_sheet", text="Delete", icon="TRASH")
        material, _collection = find_sheet(props.selected_sheet)
        if material is not None:
            length = format_mm(material.get("fc_length_mm", 0))
            width = format_mm(material.get("fc_width_mm", 0))
            thickness = format_mm(material.get("fc_thickness_mm", 0))
            if material.get("fc_has_texture"):
                grain = "length" if material.get("fc_texture_direction") == "LENGTH" else "width"
                extra = f"grain along {grain}"
            else:
                extra = "no texture"
            layout.label(text=f"{length}×{width}×{thickness} mm, {extra}")


class FC_PT_Piece(bpy.types.Panel):
    bl_label = "New Piece"
    bl_idname = "FC_PT_piece"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Furniture Cut"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        props = context.scene.fc_piece
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(props, "length_mm", text="Length (mm)")
        layout.prop(props, "width_mm", text="Width (mm)")
        layout.prop(props, "sheet_name", text="Material")
        layout.prop(props, "direction")

        material, _collection = find_sheet(props.sheet_name)
        layout.use_property_split = False
        if material is not None:
            thickness = format_mm(material.get("fc_thickness_mm", 0))
            layout.label(text=f"Thickness {thickness} mm, from the sheet")
            fits = piece_fits(
                props.length_mm,
                props.width_mm,
                float(material.get("fc_length_mm", 0)),
                float(material.get("fc_width_mm", 0)),
                props.direction,
            )
            note = layout.row()
            note.alert = not fits
            if fits:
                note.label(text="Fits on the sheet", icon="CHECKMARK")
            else:
                note.label(text="Does not fit on the sheet", icon="ERROR")
        else:
            layout.label(text="Create a sheet first", icon="INFO")

        layout.separator()
        layout.operator("fc.create_piece", icon="MESH_PLANE")
        layout.label(text="The piece is placed at the 3D cursor.", icon="CURSOR")


class FC_PT_EditPiece(bpy.types.Panel):
    bl_label = "Edit Piece"
    bl_idname = "FC_PT_edit_piece"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Furniture Cut"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        obj = active_piece(context)
        if obj is None:
            layout.label(text="Select a piece", icon="INFO")
            return

        props = context.scene.fc_edit
        layout.label(text=obj.name, icon="MESH_CUBE")
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(props, "length_mm", text="Length (mm)")
        layout.prop(props, "width_mm", text="Width (mm)")
        layout.prop(props, "sheet_name", text="Material")
        layout.prop(props, "direction")

        material, _collection = find_sheet(props.sheet_name)
        layout.use_property_split = False
        if material is not None:
            thickness = format_mm(material.get("fc_thickness_mm", 0))
            layout.label(text=f"Thickness {thickness} mm, from the sheet")
            fits = piece_fits(
                props.length_mm,
                props.width_mm,
                float(material.get("fc_length_mm", 0)),
                float(material.get("fc_width_mm", 0)),
                props.direction,
            )
            if not props.status:
                note = layout.row()
                note.alert = not fits
                if fits:
                    note.label(text="Fits on the sheet", icon="CHECKMARK")
                else:
                    note.label(text="Does not fit on the sheet", icon="ERROR")
            pending = piece_name(
                props.direction, props.length_mm, props.width_mm, material.name
            )
            if pending != obj.name:
                layout.label(text=f"Save renames this to {pending}")
        if props.status:
            alert = layout.row()
            alert.alert = True
            alert.label(text=props.status, icon="ERROR")

        layout.separator()
        layout.operator("fc.save_piece", icon="FILE_TICK")
        layout.label(text="Save renames the piece and moves it into the material folder.")


classes = (
    FC_PT_Sheet,
    FC_PT_Piece,
    FC_PT_EditPiece,
)


def register():
    for cls in classes:
        register_addon_class(cls)


def unregister():
    for cls in reversed(classes):
        unregister_addon_class(cls)
