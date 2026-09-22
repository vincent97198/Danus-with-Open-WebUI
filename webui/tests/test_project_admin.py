"""Regression tests for immediate stopping and recoverable project removal."""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import httpx
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from danus.orchestration import cli
from danus.execution import layout
import server


class ProjectControlTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'projects'
        self.project = self.root / 'old_project'
        self.worker = self.project / 'workers' / 'high'
        self.worker.mkdir(parents=True)
        (self.project / 'PROBLEM.md').write_text('original problem', encoding='utf-8')
        (self.worker / 'TASK.md').write_text('original task', encoding='utf-8')
        (self.worker / '.status.json').write_text(json.dumps({'state': 'created', 'round': 0}))
        self.env = patch.dict(os.environ, {'DANUS_AGENTS_ROOT': str(self.root)})
        self.env.start()
        self.api = patch.object(server, 'DANUS_STATUS_API', '')
        self.api.start()
        self.processes = []

    def tearDown(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        self.api.stop()
        self.env.stop()
        self.temp.cleanup()

    def start_disposable_worker(self):
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'], start_new_session=True)
        self.processes.append(proc)
        (self.worker / '.pid').write_text(str(proc.pid))
        (self.worker / '.status.json').write_text(json.dumps({'state': 'running', 'round': 2, 'round_started_at': time.time()}))
        return proc

    async def test_trash_roundtrip_retains_results_and_task(self):
        facts = self.project / 'fact_graph' / 'facts'
        facts.mkdir(parents=True)
        (facts / '1234567890abcdef.md').write_text('preserved proof', encoding='utf-8')
        result = await server.delete_project('old_project')
        self.assertTrue(result['recoverable'])
        self.assertFalse(self.project.exists())
        items = await server.list_trash()
        self.assertEqual(items[0]['id'], result['trash_id'])
        await server.restore_project(result['trash_id'])
        self.assertEqual((facts / '1234567890abcdef.md').read_text(), 'preserved proof')
        self.assertEqual((self.worker / 'TASK.md').read_text(), 'original task')
        self.assertEqual(await server.list_trash(), [])

    async def test_running_project_cannot_be_removed(self):
        proc = self.start_disposable_worker()
        with self.assertRaises(HTTPException) as error:
            await server.delete_project('old_project')
        self.assertEqual(error.exception.status_code, 409)
        self.assertIsNone(proc.poll())
        self.assertTrue(self.project.is_dir())

    async def test_start_lock_prevents_removal(self):
        with (self.worker / '.pid.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaises(HTTPException) as error:
                await server.delete_project('old_project')
            self.assertEqual(error.exception.status_code, 409)
        self.assertTrue(self.project.is_dir())

    async def test_restore_never_overwrites_existing_project(self):
        result = await server.delete_project('old_project')
        self.project.mkdir()
        (self.project / 'keep.txt').write_text('new project')
        with self.assertRaises(HTTPException) as error:
            await server.restore_project(result['trash_id'])
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual((self.project / 'keep.txt').read_text(), 'new project')
        self.assertEqual(len(await server.list_trash()), 1)

    async def test_permanent_delete_api_only_removes_selected_trash_entry(self):
        result = await server.delete_project('old_project')
        entry = server.trash_root() / result['trash_id']
        other_entry = server.trash_root() / ('f' * 32)
        other_entry.mkdir()
        (other_entry / 'keep.txt').write_text('another trash entry')
        outside = self.root / 'active_project'
        outside.mkdir()
        (outside / 'keep.txt').write_text('active project data')
        (entry / 'project' / 'external-link').symlink_to(outside, target_is_directory=True)
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            response = await client.request('DELETE', '/api/danus/trash/' + result['trash_id'],
                                            json={'confirm': True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['recoverable'])
        self.assertFalse(entry.exists())
        self.assertEqual((outside / 'keep.txt').read_text(), 'active project data')
        self.assertEqual((other_entry / 'keep.txt').read_text(), 'another trash entry')
        self.assertEqual(await server.list_trash(), [])

    async def test_permanent_delete_cannot_touch_restored_project(self):
        result = await server.delete_project('old_project')
        await server.restore_project(result['trash_id'])
        with self.assertRaises(HTTPException) as error:
            await server.purge_project(result['trash_id'], server.PurgeTrash(confirm=True))
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual((self.project / 'PROBLEM.md').read_text(), 'original problem')

    async def test_permanent_delete_rejects_paths_and_symlinks(self):
        with self.assertRaises(HTTPException) as error:
            await server.purge_project('../projects', server.PurgeTrash(confirm=True))
        self.assertEqual(error.exception.status_code, 404)
        result = await server.delete_project('old_project')
        entry = server.trash_root() / result['trash_id']
        project_data = entry / 'project'
        moved_data = Path(self.temp.name) / 'saved-data'
        project_data.rename(moved_data)
        project_data.symlink_to(moved_data, target_is_directory=True)
        with self.assertRaises(HTTPException) as error:
            await server.purge_project(result['trash_id'], server.PurgeTrash(confirm=True))
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual((moved_data / 'PROBLEM.md').read_text(), 'original problem')

    async def test_restore_and_permanent_delete_share_an_operation_lock(self):
        result = await server.delete_project('old_project')
        lock_path = server.trash_root() / '.operations.lock'
        with lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for operation in (
                server.restore_project(result['trash_id']),
                server.purge_project(result['trash_id'], server.PurgeTrash(confirm=True)),
            ):
                with self.assertRaises(HTTPException) as error:
                    await operation
                self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(await server.list_trash()), 1)

    async def test_immediate_stop_terminates_process_and_preserves_work(self):
        proc = self.start_disposable_worker()
        (self.worker / '.stop').touch()
        result = await server.stop_project('old_project')
        proc.wait(timeout=3)
        self.assertEqual(result['status'], 'stopped')
        self.assertFalse(result['workers'][0]['alive'])
        self.assertEqual(result['workers'][0]['state'], 'stopped')
        self.assertFalse((self.worker / '.stop').exists())
        self.assertEqual((self.worker / 'TASK.md').read_text(), 'original task')

    async def test_after_round_requests_stop_without_killing(self):
        proc = self.start_disposable_worker()
        result = await server.stop_project('old_project', server.StopProject(mode='after_round'))
        self.assertEqual(result['status'], 'stopping')
        self.assertIsNone(proc.poll())
        self.assertTrue((self.worker / '.stop').exists())
        progress = await server.project_progress('old_project')
        self.assertTrue(progress['workers'][0]['stop_requested'])

    async def test_rename_during_execution_keeps_problem_and_task(self):
        proc = self.start_disposable_worker()
        await server.update_project('old_project', server.ProjectUpdate(title='\u4e2d\u6587\u5c08\u6848'))
        self.assertIsNone(proc.poll())
        self.assertEqual((self.project / 'PROBLEM.md').read_text(), 'original problem')
        self.assertEqual((self.worker / 'TASK.md').read_text(), 'original task')
        self.assertEqual((await server.project('old_project'))['title'], '\u4e2d\u6587\u5c08\u6848')

    async def test_paths_and_project_symlinks_are_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.root / 'link').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HTTPException):
            await server.delete_project('link')
        with self.assertRaises(HTTPException):
            await server.delete_project('../outside')
        with self.assertRaises(HTTPException):
            await server.restore_project('../outside')
        self.assertTrue(outside.is_dir())

    def test_activity_separates_model_updates_from_command_output(self):
        lines = ['codex', 'Starting verification.', 'exec', 'cat source.py',
                 'def internal_function():', '    return 123', 'thinking',
                 'private scratch text', 'codex', 'Finished. api_key=example-secret-key']
        events = server.activity_events(lines, 'high', 1)
        self.assertEqual(len(events), 2)
        self.assertIn('Starting verification.', events[1]['text'])
        visible = str(events)
        self.assertNotIn('internal_function', visible)
        self.assertNotIn('private scratch', visible)
        self.assertNotIn('example-secret-key', visible)


if __name__ == '__main__':
    unittest.main()
