"""Bounded numerical inputs, not a code, deck, path, or command interface."""
import hashlib
import json
import math

MODEL = "devsim-pn-1d-300K-v1"
DEFAULT = {"lengthUm": 2.0, "acceptorsCm3": 1e16, "donorsCm3": 1e16,
           "areaUm2": 10.0, "voltageV": 0.4, "intervals": 200}
LIMITS = {"lengthUm": (1, 10), "acceptorsCm3": (1e15, 1e17),
          "donorsCm3": (1e15, 1e17), "areaUm2": (1, 100), "voltageV": (0, 0.5)}

def validate_input(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise ValueError("input-shape")
    result = {}
    for key, (minimum, maximum) in LIMITS.items():
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (float, int)) or not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError("input-range")
        result[key] = float(number)
    if type(value["intervals"]) is not int or value["intervals"] not in {100, 200, 400}:
        raise ValueError("mesh-range")
    result["intervals"] = value["intervals"]
    return result

def strict_json(source, maximum_bytes=8192):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result or key in {"__proto__", "constructor", "prototype"}:
                raise ValueError("duplicate-key")
            result[key] = value
        return result
    if len(source) > maximum_bytes:
        raise ValueError("input-size")
    return json.loads(source, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def validate_job_input(value):
    if isinstance(value, dict) and "model" in value:
        from .mos_contract import validate_mos
        return validate_mos(value)
    return validate_input(value)
