"""2D native acceptance and SUPREM transfer contracts. Synthetic STR is not process evidence."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from backend.app.experimental.contract import canonical
from backend.app.experimental.mos_contract import DEFAULT, validate_mos
from backend.app.experimental.service import LaboratoryApi, run_solver
from backend.app.experimental.suprem import interpolate_profile, parse_structure
from backend.app.experimental.suprem_process import deck, execute
from backend.app.experimental.suprem_container import command, decode_output
from backend.app.experimental.replay import compare, read_record

STR = b"""v SUPREM-IV.GS B.9305
D 2 3 3
c 1 0 0 0
c 2 2 0 0
c 3 2 0.5 0
c 4 0 0.5 0
r 9 3
t 1 9 1 2 3 -1 -1 -1 -1 -1
t 2 9 1 3 4 -1 -1 -1 -1 -1
s 5 24 23 20 5 2
n 0 3 999 1e16 1e17 1e16 1e17
n 1 3 999 1e16 1e17 1e16 1e17
n 2 3 999 1e16 0 1e16 0
n 3 3 999 1e16 0 1e16 0
"""

class MosContractTests(unittest.IsolatedAsyncioTestCase):
    def test_container_contract_is_pinned_offline_mount_free_and_output_strict(self):
        argv=command("podman","sha256:"+"a"*64,"opentcad-exp-test")
        for flag in ("--pull=never","--network=none","--read-only","--cap-drop=ALL","--security-opt=no-new-privileges","--pids-limit=64","--memory=512m","--cpus=1"):
            self.assertIn(flag,argv)
        self.assertFalse(any("--mount" in a or "--volume" in a for a in argv))
        with self.assertRaises(ValueError):command("podman","image:latest","name")
        names=["suprem","data/suprem.uk","data/modelrc","data/sup4gs.imp"]
        data=b'OPENTCAD_FILES_BEGIN\n'+b'\n'.join(("a"*64+"  /opt/suprem4gs/"+name).encode() for name in names)+b'\nOPENTCAD_FILES_END\n'
        data+=b'OPENTCAD_STR_BEGIN\n'+STR+b'\nOPENTCAD_STR_END\n'
        self.assertEqual(decode_output(data)[1]["sourceSha256"],parse_structure(STR)["sourceSha256"])
        with self.assertRaises(ValueError):decode_output(data+b'OPENTCAD_STR_BEGIN\n')

    async def test_process_cli_contract_records_hashes_without_claiming_native_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            executable=root/"suprem";executable.write_bytes(b"not-a-real-solver")
            data=root/"data";data.mkdir()
            for name in ("suprem.uk","modelrc","sup4gs.imp"):(data/name).write_bytes(b"test-data")
            child=MagicMock();child.returncode=0
            child.stdin.drain=AsyncMock();child.wait=AsyncMock(return_value=0)
            child.stdout.read=AsyncMock(return_value=b"")
            async def launch(*args,**kwargs):
                self.assertEqual(args,(str(executable.resolve()),))
                self.assertNotIn("shell",kwargs)
                (Path(kwargs["cwd"])/"process.str").write_bytes(STR)
                return child
            with patch("asyncio.create_subprocess_exec",side_effect=launch):
                record=await execute(executable,data,root/"output")
            self.assertEqual(record["structureSha256"],parse_structure(STR)["sourceSha256"])
            self.assertFalse(record["productApproved"])
            self.assertEqual((root/"output"/"process.str").read_bytes(),STR)
            self.assertIn(b"implant phosphorus",child.stdin.write.call_args.args[0])
            with self.assertRaises(FileExistsError):await execute(executable,data,root/"output")

    async def test_process_cli_timeout_kills_and_reaps_child_without_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);executable=root/"suprem";executable.write_bytes(b"fake")
            for name in ("suprem.uk","modelrc","sup4gs.imp"):(root/name).write_bytes(b"data")
            child=MagicMock();child.returncode=None;child.stdin.drain=AsyncMock()
            async def read(_):await asyncio.sleep(10)
            async def wait():child.returncode=-1;return -1
            child.stdout.read=read;child.wait=AsyncMock(side_effect=wait)
            with patch("asyncio.create_subprocess_exec",new=AsyncMock(return_value=child)):
                with self.assertRaises(TimeoutError):await execute(executable,root,root/"out",timeout=.001)
            child.kill.assert_called_once();child.wait.assert_awaited_once()
            self.assertFalse((root/"out"/"process.json").exists())

    def test_bounded_input_and_code_owned_deck(self):
        self.assertEqual(validate_mos(DEFAULT),DEFAULT)
        for patch in ({"gateV":float("nan")},{"refinement":True},{"refinement":3},{"command":"id"},{"dopingMode":"code"}):
            with self.assertRaises(ValueError):validate_mos({**DEFAULT,**patch})
        self.assertIn("structure out=process.str",deck())
        self.assertIn("dose=2e+14",deck(dose=2e14))
        with self.assertRaises(ValueError):deck(dose="1; id")

    def test_active_species_material_indices_interpolation_and_no_extrapolation(self):
        profile=parse_structure(STR)
        self.assertEqual(interpolate_profile(profile,[(0,0),(2,.5),(1,.25)]),[9e16,-1e16,4e16])
        # Oxide duplicate at interface must not replace silicon active doping.
        self.assertEqual(parse_structure(STR+b'n 0 1 0 1 2 3 4\n')["cells"],profile["cells"])
        with self.assertRaises(ValueError):interpolate_profile(profile,[(3,0)])
        for bad in (STR.replace(b'D 2 3 3',b'D 1 2 2'),STR.replace(b'24 23 20 5 2',b'24 23 99 5 2'),
                    STR+b'c 1 0 0 0\n',STR.replace(b'c 1 0 0 0',b'c 1 nan 0 0'),STR.replace(b'n 0 3 999',b'n 0 3 999 1'),
                    STR.replace(b't 1 9 1 2 3',b't 1 9 1 1 3'),STR.replace(b'B.9305',b'unknown'),STR+b'exec id\n'):
            with self.assertRaises(ValueError):parse_structure(bad)

    async def test_service_admission_and_no_implicit_process_fallback(self):
        seen=[]
        async def runner(value):seen.append(value);return {"computed":True}
        api=LaboratoryApi(runner=runner)
        identifier=str(uuid4())
        self.assertEqual((await api.handle("POST","/v1/lab/jobs",canonical({"requestId":identifier,"input":{**DEFAULT,"dopingMode":"suprem"}})))[0],409)
        self.assertEqual((await api.handle("POST","/v1/lab/jobs",canonical({"requestId":identifier,"input":DEFAULT})))[0],200)
        await asyncio.gather(*api.tasks.values())
        self.assertEqual(seen,[DEFAULT])
        await api.close()

@unittest.skipUnless(os.environ.get("OPENTCAD_TEST_DEVSIM")=="1","requires explicitly installed DEVSIM 2.11.0")
class MosNumericalTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_2d_gate_response_width_mesh_conservation_and_replay(self):
        normal=await run_solver(DEFAULT)
        repeat=await run_solver(DEFAULT)
        fine=await run_solver({**DEFAULT,"refinement":2})
        off=await run_solver({**DEFAULT,"gateV":0})
        wide=await run_solver({**DEFAULT,"widthUm":20})
        # Native sparse solvers may vary last bits. Replay is tolerance-based.
        self.assertTrue(compare(normal,repeat)["numericallyReproduced"])
        current=normal["iv"][-1][1]
        error=abs(current/fine["iv"][-1][1]-1)
        print("MOS benchmark:",current,"A; mesh relative error",error,"; off current",off["iv"][-1][1],flush=True)
        self.assertGreater(current,10*abs(off["iv"][-1][1]))
        self.assertAlmostEqual(wide["iv"][-1][1]/current,2,places=7)
        self.assertLess(error,.1)
        for r in (normal,repeat,fine,off,wide):
            self.assertLessEqual(r["checks"]["maxCurrentToleranceRatio"],1)
            self.assertLess(abs(r["iv"][0][1]),1e-12)
            self.assertGreater(len(r["regions"]["silicon"]["triangles"]),100)
            self.assertGreater(len(set(r["regions"]["silicon"]["yUm"])),10)
            self.assertTrue(all(b[1]>a[1] for a,b in zip(r["iv"],r["iv"][1:])))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"result.json";path.write_bytes(canonical(normal))
            self.assertTrue(compare(read_record(path),repeat)["numericallyReproduced"])
            tamper={**normal,"iv":[[0,999]]};path.write_bytes(canonical(tamper))
            with self.assertRaises(ValueError):read_record(path)

    async def test_synthetic_str_transfer_into_actual_2d_solve_not_process_evidence(self):
        normal=await run_solver(DEFAULT)
        si=normal["regions"]["silicon"]
        lines=["v SUPREM-IV.GS B.9305","D 2 3 3","r 7 3"]
        lines += [f"c {i+1} {x:.17g} {y:.17g} 0" for i,(x,y) in enumerate(zip(si["xUm"],si["yUm"]))]
        lines += [f"t {i+1} 7 {a+1} {b+1} {c+1} -1 -1 -1 -1 -1" for i,(a,b,c) in enumerate(si["triangles"])]
        lines += ["s 2 20 23"]
        lines += [f"n {i} 3 {max(v,0):.17g} {max(-v,0):.17g}" for i,v in enumerate(si["netDopingCm3"])]
        profile=parse_structure("\n".join(lines).encode("ascii"))
        imported=await run_solver({**DEFAULT,"dopingMode":"suprem"},process_profile=profile)
        self.assertAlmostEqual(imported["iv"][-1][1]/normal["iv"][-1][1],1,places=6)
        self.assertEqual(imported["dopingSource"]["sourceSha256"],profile["sourceSha256"])
        self.assertFalse(imported["dopingSource"]["processSimulated"])

    async def test_native_2d_cancellation_releases_single_job_slot(self):
        api=LaboratoryApi()
        identifier=str(uuid4())
        await api.handle("POST","/v1/lab/jobs",canonical({"requestId":identifier,"input":{**DEFAULT,"refinement":2}}))
        await asyncio.sleep(.1)
        status,record=await api.handle("POST",f"/v1/lab/jobs/{identifier}/cancel",b'{}')
        self.assertEqual((status,record["state"]),(200,"cancelled"))
        self.assertTrue(all(task.done() for task in api.tasks.values()))
        next_id=str(uuid4())
        await api.handle("POST","/v1/lab/jobs",canonical({"requestId":next_id,"input":DEFAULT}))
        await asyncio.gather(*api.tasks.values())
        self.assertEqual(api.jobs[next_id]["state"],"complete")
        await api.close()
