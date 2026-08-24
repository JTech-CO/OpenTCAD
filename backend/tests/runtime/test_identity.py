"""BRK-007 policy-derived job identity tests."""

from dataclasses import replace
import unittest

from backend.app.runtime.mock_backend import full_mock_capabilities
from backend.app.runtime.models import JobIdentity, JobKind
from backend.app.runtime.policy import EngineProfile, SandboxPolicy
from backend.tests.runtime.support import MAXIMUM_LIMITS, POLICY, PROFILE, make_spec


class JobIdentityTests(unittest.TestCase):
    def test_every_job_kind_uses_the_same_label_and_object_name_contract(self) -> None:
        job_id = "00000000-0000-4000-8000-000000000420"
        profiles = tuple(
            EngineProfile(
                profile_id=f"identity-{kind.value}",
                kind=kind,
                image=PROFILE.image,
                environment_profile=PROFILE.environment_profile,
                entrypoint_id=PROFILE.entrypoint_id,
                required_inputs=PROFILE.required_inputs,
                expected_outputs=PROFILE.expected_outputs,
            )
            for kind in JobKind
        )
        policy = SandboxPolicy(
            version=POLICY.version,
            engine_profiles=profiles,
            maximum_limits=MAXIMUM_LIMITS,
            maximum_input_bytes=POLICY.maximum_input_bytes,
        )
        identities = []
        for profile in profiles:
            spec = replace(
                make_spec(job_id),
                profile_id=profile.profile_id,
                kind=profile.kind,
            )
            validated = policy.validate(spec, full_mock_capabilities())
            identities.append(validated.identity)
            self.assertIn(validated.identity.label, validated.labels)

        expected = JobIdentity(job_id)
        self.assertEqual(identities, [expected] * len(profiles))
        self.assertEqual(expected.label, ("tcad.job_id", job_id))
        self.assertEqual(expected.object_name, f"opentcad-job-{job_id}")
        self.assertEqual(expected.volume_name, f"opentcad-job-{job_id}-data")


if __name__ == "__main__":
    unittest.main()
