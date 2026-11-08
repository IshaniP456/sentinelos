"""Portable model-facing tool declaration. Author: Tishneet.

Nova's top-level schema accepts type/properties/required only. The complete
backend schema and independent validator remain authoritative; do not mistake
the reduced model declaration for policy or validation enforcement.
"""
import copy


def converse_tool_schema(schema):
    result = {}
    for key in ("type", "required", "enum"):
        if key in schema:
            result[key] = copy.deepcopy(schema[key])
    if "const" in schema:
        result["enum"] = [copy.deepcopy(schema["const"])]
    if "properties" in schema:
        result["properties"] = {name: converse_tool_schema(value)
                                for name, value in schema["properties"].items()}
    if "items" in schema:
        result["items"] = converse_tool_schema(schema["items"])
    return result
