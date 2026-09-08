"""MVP scope, persisted jobs, offline backups and actual Windows containment."""
import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.app.experimental.contract import DEFAULT, MODEL, canonical, digest
from backend.app.experimental.history import History, read_backup, validate_record
from backend.app.experimental.service import LaboratoryApi, run_solver
from backend.app.experimental.windows_mvp import doctor, parser, run, safe_path
from backend.app.service.instance import LocalInstance, LocalInstanceAlreadyRunning


def complete_result():
    result = {"format":"opentcad-solver-result", "model":MODEL, "schemaVersion":1,
              "input":DEFAULT, "inputSha256":digest(DEFAULT), "productApproved":False}
    result["resultSha256"] = digest(result)
    return result


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = History(self.root / "history.sqlite3")

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_complete_cancel_restart_backup_restore_and_idempotence(self):
        async def solver(_): return complete_result()
        api = LaboratoryApi(runner=solver, store=self.store)
        identifier = str(uuid4())
        request = canonical({"requestId":identifier, "input":DEFAULT})
        self.assertEqual((await api.handle("POST", "/v1/lab/jobs", request))[0], 200)
        await asyncio.sleep(0)
        await api.close()
        restarted = LaboratoryApi(runner=solver, store=self.store)
        self.assertEqual((await restarted.handle("POST", "/v1/lab/jobs", request))[1]["state"], "complete")
        self.assertEqual((await restarted.handle("POST", f"/v1/lab/jobs/{identifier}/cancel", b'{}'))[1]["state"], "complete")
        pending = {"requestId":str(uuid4()), "inputSha256":digest(DEFAULT), "state":"running"}
        self.store.save(pending)
        recovered = LaboratoryApi(store=self.store)
        self.assertEqual(recovered.jobs[pending["requestId"]]["error"], "interrupted")
        target = self.root / "backup.json"
        self.store.backup(target)
        with self.assertRaises(FileExistsError): self.store.backup(target)
        records = read_backup(target)
        other = History(self.root / "other.sqlite3")
        try:
            other.restore(records)
            self.assertEqual(other.load(), self.store.load())
            with self.assertRaises(ValueError): other.restore(records)
        finally: other.close()
        await restarted.close(); await recovered.close()

    async def test_cancel_before_start_and_graceful_shutdown_persist(self):
        async def wait(_): await asyncio.sleep(60)
        api = LaboratoryApi(runner=wait, store=self.store)
        identifier = str(uuid4())
        await api.handle("POST", "/v1/lab/jobs", canonical({"requestId":identifier, "input":DEFAULT}))
        await api.close()
        self.assertEqual(self.store.load()[identifier]["state"], "cancelled")

    async def test_write_failure_prevents_execution_and_success_acknowledgement(self):
        calls = []
        async def solver(_): calls.append(True); return complete_result()
        api = LaboratoryApi(runner=solver, store=self.store)
        with patch.object(self.store, "save", side_effect=OSError("private location")):
            response = await api.handle("POST", "/v1/lab/jobs", canonical({"requestId":str(uuid4()), "input":DEFAULT}))
            self.assertEqual(response[0], 503)
        await asyncio.sleep(0)
        self.assertEqual(calls, [])
        self.assertNotIn("private", json.dumps(response))
        api = LaboratoryApi(runner=solver, store=self.store)
        identifier = str(uuid4())
        await api.handle("POST", "/v1/lab/jobs", canonical({"requestId":identifier, "input":DEFAULT}))
        with patch.object(self.store, "save", side_effect=OSError()):
            await asyncio.sleep(0)
        self.assertEqual(api.jobs[identifier]["state"], "failed")
        self.assertNotIn("result", api.jobs[identifier])
        self.assertTrue(api.storage_failed)
        await api.close()

    async def test_corruption_duplicates_and_nonterminal_results_rejected(self):
        record = {"requestId":str(uuid4()), "inputSha256":digest(DEFAULT), "state":"complete", "result":complete_result()}
        self.store.save(record)
        invalid = copy.deepcopy(record); invalid["result"]["input"]["voltageV"] = .2
        with self.assertRaises(ValueError): validate_record(invalid)
        invalid = dict(record, state="cancelled")
        with self.assertRaises(ValueError): validate_record(invalid)
        self.store.db.execute("UPDATE jobs SET sha256='bad'"); self.store.db.commit()
        with self.assertRaises(ValueError): self.store.load()
        target = self.root / "bad.json"
        target.write_bytes(b'{"schemaVersion":1,"schemaVersion":1}')
        with self.assertRaises(ValueError): read_backup(target)
        value = {"format":"opentcad-windows-mvp-backup", "schemaVersion":1, "records":[record,record]}
        value["sha256"] = digest(value); target.write_bytes(canonical(value))
        with self.assertRaises(ValueError): read_backup(target)

    async def test_capacity_and_exclusive_lock(self):
        for _ in range(32): self.store.save({"requestId":str(uuid4()), "inputSha256":digest(DEFAULT), "state":"cancelled"})
        with self.assertRaises(ValueError): self.store.save({"requestId":str(uuid4()), "inputSha256":digest(DEFAULT), "state":"running"})
        with LocalInstance(self.root / "instance.lock", self.root / "unused.json"):
            with self.assertRaises(LocalInstanceAlreadyRunning):
                LocalInstance(self.root / "instance.lock", self.root / "unused.json").acquire()


class ScopeTests(unittest.TestCase):
    def test_candidate_is_not_m3_and_doctor_does_not_create_state(self):
        report = doctor(Path("not-built"))
        self.assertFalse(report["prerequisitesReady"])
        self.assertFalse(report["m3Approved"])
        self.assertFalse(report["productEnabled"])
        manifest = json.loads(Path("validation/manifests/windows-mvp-release.json").read_text())
        self.assertEqual(manifest["status"], "candidate-not-released")
        self.assertFalse(manifest["releaseReview"]["approved"])
        m3 = json.loads(Path("validation/manifests/m3-entry-gates.json").read_text())
        self.assertFalse(m3["productEnabled"])

    def test_relative_and_parent_paths_rejected(self):
        for value in (Path("relative"), Path.cwd() / ".." / "escape"):
            with self.assertRaises(ValueError): safe_path(value)

    @unittest.skipUnless(sys.platform == "win32", "Windows release CLI")
    def test_restore_never_overwrites_and_backup_is_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / "source"; state.mkdir()
            store = History(state / "history.sqlite3"); store.close()
            backup = root / "backup.json"
            with LocalInstance(state / "instance.lock", state / "unused-endpoint.json"):
                with self.assertRaises(LocalInstanceAlreadyRunning): run(parser().parse_args(["backup", "--state-directory", str(state), "--file", str(backup)]))
            self.assertFalse(backup.exists())
            self.assertEqual(run(parser().parse_args(["backup", "--state-directory", str(state), "--file", str(backup)])), 0)
            target = root / "restored"
            args = parser().parse_args(["restore", "--state-directory", str(target), "--file", str(backup)])
            self.assertEqual(run(args), 0)
            with self.assertRaises(ValueError): run(args)


@unittest.skipUnless(sys.platform == "win32", "Real Windows Job Object")
class WindowsContainmentTests(unittest.TestCase):
    def test_hard_service_exit_kills_solver_descendant(self):
        for target in ("service", "launcher"):
            with self.subTest(target=target): self._exercise(target)

    def _exercise(self, target):
        code = "from backend.app.experimental.windows_job import contain_current_process; import os,subprocess,sys; contain_current_process(); p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(os.getpid(),p.pid,flush=True); sys.stdin.read()"
        parent = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            # communicate is bounded even if native containment setup fails.
            import queue
            import threading
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(parent.stdout.readline()), daemon=True).start()
            line = lines.get(timeout=15)
            self.assertTrue(line, parent.stderr.read() if parent.poll() is not None else "missing PID")
            actual_parent, child = map(int, line.split())
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]; kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE,wintypes.UINT]
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            service = kernel.OpenProcess(0x100001,False,actual_parent)
            descendant = kernel.OpenProcess(0x100000,False,child)
            try:
                self.assertTrue(service and descendant)
                if target == "service": self.assertTrue(kernel.TerminateProcess(service,73))
                else: parent.kill()
                self.assertEqual(kernel.WaitForSingleObject(descendant,10000),0)
            finally:
                if service: kernel.CloseHandle(service)
                if descendant: kernel.CloseHandle(descendant)
            parent.wait(timeout=10)
        finally:
            if parent.poll() is None: parent.kill()
            parent.communicate(timeout=10)


@unittest.skipUnless(os.environ.get("OPENTCAD_TEST_DEVSIM") == "1", "user-installed solver")
class NativeHistoryTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(sys.platform == "win32", "actual Windows worker containment")
    async def test_cancellation_kills_actual_worker_not_only_venv_launcher(self):
        from backend.app.experimental.windows_job import ChildJob
        from backend.app.experimental.mos_contract import DEFAULT as MOS_DEFAULT
        jobs = []
        def create(pid):
            job = ChildJob(pid); jobs.append(job); return job
        with patch("backend.app.experimental.windows_job.ChildJob", side_effect=create):
            task = asyncio.create_task(run_solver(dict(MOS_DEFAULT, refinement=2, gateV=1.5)))
            try:
                deadline = time.monotonic()+15
                while not jobs and not task.done() and time.monotonic()<deadline: await asyncio.sleep(.01)
                self.assertTrue(jobs)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                # ChildJob.close waits on the real worker handle before returning.
                self.assertIsNone(jobs[0].handle)
            finally:
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_actual_result_survives_backup_restore(self):
        result = await run_solver(DEFAULT)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); first = History(root / "first.sqlite3"); second = History(root / "second.sqlite3")
            try:
                record = {"requestId":str(uuid4()), "inputSha256":digest(DEFAULT), "state":"complete", "result":result}
                first.save(record); first.backup(root / "backup.json")
                second.restore(read_backup(root / "backup.json"))
                self.assertEqual(second.load()[record["requestId"]]["result"],result)
            finally: first.close(); second.close()


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("OPENTCAD_TEST_DEVSIM") == "1", "Windows with user-installed solver")
class WindowsServiceAcceptanceTests(unittest.TestCase):
    def test_actual_cli_http_restart_interruption_export_and_backup(self):
        import queue
        import threading
        from urllib.parse import urlsplit
        from urllib.request import Request, urlopen
        from backend.app.experimental.mos_contract import DEFAULT as MOS_DEFAULT

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / "state"
            # A minimal static index is enough for the HTTP service contract;
            # the full repository frontend is separately built and tested.
            assets = root / "assets"; assets.mkdir(); (assets / "index.html").write_text("<!doctype html><title>Test</title>")
            environment = dict(os.environ); environment.pop("OPENTCAD_MVP_PARENT_PID", None)
            process = None

            def stop():
                nonlocal process
                if process is not None:
                    if process.poll() is None: process.kill()
                    process.wait(timeout=15)
                    process = None

            def start():
                nonlocal process
                command = [sys.executable, "-m", "backend.app.experimental.windows_mvp", "serve", "--state-directory", str(state), "--assets", str(assets)]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=environment)
                lines = queue.Queue()
                stream = process.stdout
                def read_lines():
                    with stream:
                        for line in stream: lines.put(line)
                threading.Thread(target=read_lines, daemon=True).start()
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    try: line = lines.get(timeout=.2).strip()
                    except queue.Empty:
                        if process.poll() is not None: self.fail("MVP startup failed")
                        continue
                    if line.startswith("http://127.0.0.1:"):
                        url = urlsplit(line)
                        return "http://" + url.netloc, url.fragment.removeprefix("experiment=")
                self.fail("MVP startup timeout")

            def request(base, token, path, value=None):
                body = canonical(value) if value is not None else None
                req = Request(base+path, data=body, headers={"Authorization":"Bearer "+token, "Origin":base, "Content-Type":"application/json"})
                with urlopen(req, timeout=10) as response: return json.load(response)

            def command(*args):
                return subprocess.run([sys.executable, "-m", "backend.app.experimental.windows_mvp", *args], capture_output=True, text=True, timeout=30, env=environment)

            try:
                base, token = start()
                completed = []
                for inputs in (DEFAULT, MOS_DEFAULT):
                    identifier = str(uuid4())
                    job = request(base,token,"/v1/lab/jobs",{"requestId":identifier,"input":inputs})
                    deadline = time.monotonic()+120
                    while job["state"] == "running" and time.monotonic() < deadline:
                        time.sleep(.1); job = request(base,token,"/v1/lab/jobs/"+identifier)
                    self.assertEqual(job["state"], "complete")
                    completed.append(job)
                interrupted = str(uuid4())
                request(base,token,"/v1/lab/jobs",{"requestId":interrupted,"input":dict(MOS_DEFAULT,refinement=2,gateV=1.5)})
                stop()
                # Let Job Object teardown finish before taking the directory lock.
                time.sleep(.3)
                base, token = start()
                self.assertEqual(request(base,token,"/v1/lab/jobs/"+interrupted)["error"], "interrupted")
                for previous in completed:
                    self.assertEqual(request(base,token,"/v1/lab/jobs/"+previous["requestId"]),previous)
                self.assertEqual(len(request(base,token,"/v1/lab/jobs")["jobs"]),3)
                self.assertNotEqual(command("backup","--state-directory",str(state),"--file",str(root/"locked.json")).returncode,0)
                stop(); time.sleep(.3)
                result_path = root / "result.json"
                self.assertEqual(command("export","--state-directory",str(state),"--job-id",completed[0]["requestId"],"--file",str(result_path)).returncode,0)
                self.assertEqual(json.loads(result_path.read_text()),completed[0]["result"])
                backup = root / "backup.json"
                self.assertEqual(command("backup","--state-directory",str(state),"--file",str(backup)).returncode,0)
                self.assertEqual(command("verify-backup","--file",str(backup)).returncode,0)
                restored = root / "restored"
                self.assertEqual(command("restore","--state-directory",str(restored),"--file",str(backup)).returncode,0)
                history = command("history","--state-directory",str(restored))
                self.assertEqual(history.returncode,0)
                self.assertEqual(len(json.loads(history.stdout)["jobs"]),3)
                broken = json.loads(backup.read_text()); broken["sha256"] = "0"*64; backup.write_bytes(canonical(broken))
                self.assertNotEqual(command("verify-backup","--file",str(backup)).returncode,0)
            finally: stop()
