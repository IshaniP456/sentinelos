"""Provider-neutral planning functions; independent checks remain authoritative.

Author: Tishneet
"""

import copy

from .intent import parse_instruction


class Planner:
    """Generate candidates only; the workflow validates, authorizes, and simulates."""

    def __init__(self, provider):
        self.provider = provider

    def generate_plan(self, instruction, warehouse):
        parse_instruction(instruction)
        return copy.deepcopy(self.provider.generate(instruction, copy.deepcopy(warehouse), attempt=1))

    def generate_image_plan(self, image, warehouse):
        return copy.deepcopy(self.provider.generate_image(copy.deepcopy(image), copy.deepcopy(warehouse)))

    def replan(self, instruction, failed_plan, simulation_result, warehouse, attempt):
        intent = parse_instruction(instruction)
        if type(attempt) is not int or not 2 <= attempt <= 3:
            raise ValueError("Replanning requires candidate attempt 2 or 3.")
        if simulation_result.get("passed") is not False:
            raise ValueError("Replanning requires a failed simulation.")
        if not intent["flexible"]:
            raise ValueError("The request does not permit an alternate destination.")
        forbidden = {"INVALID_WAREHOUSE_STATE", "INTERNAL_ERROR", "RESTRICTED_ZONE", "INVALID_COUNT", "INVALID_ACTION", "INVALID_PLAN"}
        if any(v.get("code") in forbidden for v in simulation_result.get("violations", [])):
            raise ValueError("This failure is not eligible for AI replanning.")
        return copy.deepcopy(self.provider.generate(
            instruction, copy.deepcopy(warehouse), failed_plan=copy.deepcopy(failed_plan),
            simulation_result=copy.deepcopy(simulation_result), attempt=attempt,
        ))
