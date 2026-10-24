"""Native Recipe column association checks against independent System data.

DrawRecipe.ui VA 10003670 checks group existence, count, binding/type and then
the exact title CString. Column zero is a control-only serial column; column
i (i >= 1) corresponds to System RecipeGroup.fields[i-1], including the
reserved recipe-name field. This module does not load any vendor code.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent




def check_recipe_association(core, definition, object_types=None):
    """Return field-level findings; titles are never translated or normalized.

    The serial-column invariants are constructor evidence, not the native
    name-comparison loop (which starts at column one). Group fields retain
    their exact multilang token when the source uses one.
    """
    errors = []
    rows = []

    def require(condition, code, **details):
        if not condition:
            errors.append(dict(code=code, **details))

    require(core.group == definition.name, "group_name",
            actual=core.group, expected=definition.name)
    require(len(core.columns) == len(definition.fields) + 1, "column_count",
            actual=len(core.columns), expected=len(definition.fields) + 1,
            native_resource_id=45)
    require(bool(definition.fields), "missing_recipe_name_field")
    if definition.fields:
        first = definition.fields[0]
        require(first.binding == "" and first.data_type == 3,
                "reserved_recipe_name_field")
    require(bool(core.columns), "missing_serial_column")
    if core.columns:
        serial = core.columns[0]
        require(serial.binding == "" and serial.title == "序号" and
                serial.values[0] == 3 and serial.values[3] == 0,
                "serial_column_constructor_invariants")
    for i, (column, field) in enumerate(zip(core.columns[1:], definition.fields), 1):
        require(column.binding == field.binding, "binding", column=i,
                actual=column.binding, expected=field.binding,
                native_resource_id=46)
        require(column.values[0] == field.data_type, "type", column=i,
                actual=column.values[0], expected=field.data_type,
                native_resource_id=47)
        require(column.title == field.title, "title", column=i,
                actual=column.title, expected=field.title,
                native_resource_id=18)
        if field.binding and object_types is not None:
            require(field.binding in object_types, "object_missing", column=i,
                    binding=field.binding)
            require(object_types.get(field.binding) == column.values[0],
                    "object_type", column=i, binding=field.binding,
                    actual=column.values[0], expected=object_types.get(field.binding))
        rows.append(dict(column=i, group_field=i-1, binding=column.binding,
                         title=column.title, data_type=column.values[0],
                         expected_binding=field.binding, expected_title=field.title,
                         expected_type=field.data_type))
    return dict(passed=not errors, group=core.group, errors=errors, columns=rows,
                serial_column=0, reserved_recipe_name_column=1,
                native_check_function="DrawRecipe.ui VA 0x10003670",
                title_comparison="VA 0x10003e7b..0x10003edf; resource 18 at 0x10003ee9")


def require_recipe_association(core, definition, object_types=None):
    result = check_recipe_association(core, definition, object_types)
    if not result["passed"]:
        raise ValueError("Native recipe association mismatch: " + repr(result["errors"]))
    return result
