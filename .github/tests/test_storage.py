import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from ctfd_monitor import app as m

class StorageTests(unittest.TestCase):
    def test_identity_lock_and_preserved_agent_instructions(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            profile = Path(d) / 'config.toml'
            profile.write_text('url="https://ctf.example"\nroot="work"\n')
            m.configure(profile)
            monitor = m.Monitor(m.SharedState(), threading.Event())
            try:
                one = monitor.normalize_challenge({'id': 1}, {'id': 1, 'name': 'same'})
                two = monitor.normalize_challenge({'id': 2}, {'id': 2, 'name': 'same'})
                self.assertNotEqual(one['directory'], two['directory'])
                monitor.previous = {'challenges': {'1': one}}
                renamed = monitor.normalize_challenge({'id': 1}, {'id': 1, 'name': 'renamed'})
                self.assertEqual(one['directory'], renamed['directory'])
                deploy = monitor.prepare_challenge(one)
                instructions = deploy.parent / 'AGENTS.md'
                instructions.write_text('my instructions')
                monitor.prepare_challenge(renamed)
                self.assertEqual(instructions.read_text(), 'my instructions')
                file = deploy / 'data'
                file.write_text('user changes')
                monitor.archive_existing(1, file)
                backups = list(m.ARCHIVE_DIR.glob('1/*/data'))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(), 'user changes')
                lock1 = m.InstanceLock(m.LOCK_FILE)
                lock2 = m.InstanceLock(m.LOCK_FILE)
                self.assertTrue(lock1.acquire())
                try:
                    self.assertFalse(lock2.acquire())
                finally:
                    lock1.release()
                self.assertTrue(lock2.acquire())
                lock2.release()
            finally:
                monitor.executor.shutdown()
