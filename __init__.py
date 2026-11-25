bl_info = {
    "name": "Furniture Cut",
    "author": "Furniture Cut",
    "version": (1, 2, 2),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Furniture Cut",
    "description": "Create sheet materials and cut rectangular pieces from them",
    "category": "Object",
}

import bpy

from . import operators, panels, properties


def register():
    properties.register()
    operators.register()
    panels.register()


def unregister():
    panels.unregister()
    operators.unregister()
    properties.unregister()
