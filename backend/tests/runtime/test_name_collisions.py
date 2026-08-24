"""Cross-platform file-name collision policy tests."""

from dataclasses import replace
import unittest

from backend.app.runtime.errors import ErrorCode, RuntimeBackendError
from backend.app.runtime.policy import EngineProfile
from backend.tests.runtime.support import PROFILE, make_spec


class FileNameCollisionTests(unittest.TestCase):
    def test_casefold_collisions_fail_before_runtime_allocation(self) -> None:
        collision = ("Result.str", "result.str")
        with self.assertRaises(RuntimeBackendError) as spec_error:
            replace(
                make_spec("00000000-0000-4000-8000-000000000421"),
                expected_outputs=collision,
            )
        self.assertEqual(spec_error.exception.code, ErrorCode.INVALID_SPEC)

        with self.assertRaises(RuntimeBackendError) as profile_error:
            EngineProfile(
                profile_id="collision-profile",
                kind=PROFILE.kind,
                image=PROFILE.image,
                environment_profile=PROFILE.environment_profile,
                entrypoint_id=PROFILE.entrypoint_id,
                required_inputs=PROFILE.required_inputs,
                expected_outputs=collision,
            )
        self.assertEqual(profile_error.exception.code, ErrorCode.INVALID_SPEC)


if __name__ == "__main__":
    unittest.main()
