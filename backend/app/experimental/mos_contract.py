"""Bounded fixed-geometry-family MOSFET contract, separate from product approval."""
import math

MODEL = "devsim-mos-2d-300K-v1"
LIMITS = {"gateLengthUm": (0.5, 2), "widthUm": (1, 100), "oxideNm": (5, 30),
          "acceptorsCm3": (1e15, 1e17), "donorsCm3": (1e17, 1e18),
          "gateV": (0, 1.5), "drainV": (0, 0.5)}
DEFAULT = {"model": MODEL, "gateLengthUm": 1., "widthUm": 10., "oxideNm": 10.,
           "acceptorsCm3": 1e16, "donorsCm3": 1e18, "gateV": 1., "drainV": .1, "refinement": 1, "dopingMode": "template"}

def validate_mos(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT) or value["model"] != MODEL:
        raise ValueError("mos-input-shape")
    result = {"model": MODEL}
    for key, (low, high) in LIMITS.items():
        number = value[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError("mos-input-range")
        result[key] = float(number)
    if type(value["refinement"]) is not int or value["refinement"] not in (1, 2):
        raise ValueError("mos-mesh-range")
    result["refinement"] = value["refinement"]
    if value["dopingMode"] not in ("template", "suprem"):
        raise ValueError("mos-doping-mode")
    result["dopingMode"] = value["dopingMode"]
    return result
