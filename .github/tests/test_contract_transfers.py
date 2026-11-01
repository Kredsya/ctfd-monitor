import io
import json
import os
import subprocess
import sys
import time
import threading
import zipfile
from pathlib import Path
from unittest.mock import patch
from scenarios import REPO, Scenario, m


def zip_bytes(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        for name,data in files: archive.writestr(name,data)
    return stream.getvalue()


class TransferContracts(Scenario):
    def test_download_checksum_restart_and_replacement_backup(self):
        challenge,file,deploy=self.download(b'first')
        self.assertTrue(self.monitor.local_file_is_current(1,file,deploy/'file.bin'))
        self.assertTrue(self.new_monitor().local_file_is_current(1,file,deploy/'file.bin'))
        (deploy/'file.bin').write_bytes(b'user modified')
        self.assertFalse(self.monitor.local_file_is_current(1,file,deploy/'file.bin'))
        self.download(b'second')
        self.assertEqual((deploy/'file.bin').read_bytes(),b'second')
        self.assertEqual([p.read_bytes() for p in m.ARCHIVE_DIR.glob('1/*/file.bin')],[b'user modified'])

    def test_short_response_keeps_previous_file_and_manifest(self):
        _,_,deploy=self.download(b'old')
        previous=m.MANIFEST_FILE.read_bytes()
        self.download(b'short',headers={'Content-Length':'100'})
        self.assertEqual((deploy/'file.bin').read_bytes(),b'old')
        self.assertEqual(m.MANIFEST_FILE.read_bytes(),previous)
        self.assertFalse(list(deploy.glob('.*ctfd-part*')))
        self.assertEqual(self.monitor.state.jobs[-1].state,'ERROR')

    def test_legacy_download_size_limit_no_longer_stops_downloads(self):
        self.profile.write_text(self.profile.read_text()+'\nmax_download_bytes = 3\n')
        m.configure(self.profile)
        _,_,deploy=self.download(b'old')
        self.download(b'larger than retired limit')
        self.assertEqual((deploy/'file.bin').read_bytes(),b'larger than retired limit')
        self.assertFalse(list(deploy.glob('.*ctfd-part*')))

    def test_cancellation_keeps_previous_file_and_removes_partial(self):
        _,_,deploy=self.download(b'old')
        self.monitor.stop.set()
        self.download(b'new')
        self.assertEqual((deploy/'file.bin').read_bytes(),b'old')
        self.assertFalse(self.monitor.active_files)
        self.assertFalse(list(deploy.glob('.*ctfd-part*')))

    def test_disk_replace_failure_preserves_previous_download(self):
        _,_,deploy=self.download(b'old')
        with patch.object(Path,'replace',side_effect=OSError('disk failure')):
            self.download(b'new')
        self.assertEqual((deploy/'file.bin').read_bytes(),b'old')
        self.assertFalse(list(deploy.glob('.*ctfd-part*')))

    def test_duplicate_scheduling_only_downloads_once(self):
        entered=threading.Event(); release=threading.Event()
        def response(handler):
            entered.set(); release.wait(5)
            return 200,b'payload',{}
        self.routes['/files/a']=response
        challenge=self.challenge(files=['/files/a']); file=challenge['files'][0]
        deploy=self.monitor.prepare_challenge(challenge)
        try:
            self.monitor.schedule_file(challenge,file,deploy,False)
            self.assertTrue(entered.wait(3))
            for _ in range(20): self.monitor.schedule_file(challenge,file,deploy,False)
        finally:
            release.set()
            self.monitor.executor.shutdown(wait=True)
        self.assertEqual(sum(path=='/files/a' for path,_ in self.requests),1)
        self.assertEqual((deploy/'a').read_bytes(),b'payload')

    def test_archive_update_removes_stale_file_and_preserves_unrelated_work(self):
        _,file,deploy=self.download(zip_bytes([('nested/a',b'old'),('stale',b'obsolete')]),'data.zip')
        (deploy/'solution.py').write_text('keep')
        self.download(zip_bytes([('nested/a',b'new')]),'data.zip')
        self.assertEqual((deploy/'nested/a').read_bytes(),b'new')
        self.assertFalse((deploy/'stale').exists())
        self.assertEqual((deploy/'solution.py').read_text(),'keep')
        self.assertTrue(self.monitor.extraction_is_current(1,file,deploy))
        self.assertFalse(list(m.STAGING_DIR.iterdir()))

    def test_failed_extraction_does_not_publish_partial_files(self):
        _,_,deploy=self.download(zip_bytes([('a',b'valid'),('../escape',b'bad')]),'bad.zip')
        self.assertFalse((deploy/'a').exists())
        self.assertFalse((deploy.parent/'escape').exists())
        self.assertNotEqual(self.monitor.manifest['1/bad.zip']['extraction']['status'],'complete')

    def test_archive_must_not_overwrite_itself(self):
        body=zip_bytes([('data.zip',b'destroy archive')])
        _,_,deploy=self.download(body,'data.zip')
        self.assertEqual((deploy/'data.zip').read_bytes(),body)

    def test_extraction_symlink_escape_is_reported_not_marked_complete(self):
        deploy=self.monitor.prepare_challenge(self.challenge())
        outside=self.root/'outside'; outside.mkdir()
        (deploy/'link').symlink_to(outside,target_is_directory=True)
        self.download(zip_bytes([('link/payload',b'bad')]),'data.zip')
        self.assertFalse((outside/'payload').exists())
        self.assertNotEqual(self.monitor.manifest['1/data.zip']['extraction']['status'],'complete')


    def test_midstream_cancellation_preserves_previous_file(self):
        _,file,deploy=self.download(b'old')
        entered=threading.Event(); release=threading.Event()
        def streaming(handler):
            handler.send_response(200); handler.send_header('Content-Length',str(256*1024)); handler.end_headers()
            handler.wfile.write(b'a'*(128*1024)); handler.wfile.flush(); entered.set()
            release.wait(5)
            try: handler.wfile.write(b'b'*(128*1024))
            except (BrokenPipeError,ConnectionResetError): pass
            return None
        self.routes['/files/file.bin']=streaming
        try:
            self.monitor.schedule_file(self.challenge(files=['/files/file.bin']),file,deploy,True)
            self.assertTrue(entered.wait(3))
            self.monitor.stop.set()
        finally:
            release.set(); self.monitor.executor.shutdown(wait=True)
        self.assertEqual((deploy/'file.bin').read_bytes(),b'old')
        self.assertFalse(list(deploy.glob('.*ctfd-part*')))

    def test_process_kill_during_download_then_restart_recovers(self):
        entered=threading.Event(); release=threading.Event()
        def streaming(handler):
            handler.send_response(200); handler.send_header('Content-Length',str(256*1024)); handler.end_headers()
            handler.wfile.write(b'a'*(128*1024)); handler.wfile.flush(); entered.set()
            release.wait(10)
            try: handler.wfile.write(b'b'*(128*1024))
            except (BrokenPipeError,ConnectionResetError): pass
            return None
        self.routes['/files/crash.bin']=streaming
        self.publish([{'id':1,'name':'Crash','files':['/files/crash.bin']}])
        # os.environ is deliberately isolated in Scenario; pass a clean absolute source path.
        env=dict(os.environ, PYTHONPATH=str(REPO/'src'))
        child=subprocess.Popen([sys.executable,'-m','ctfd_monitor','--headless','--config',str(self.profile)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        deploy=m.BASE_DIR/'Crash/chall/deploy'
        try:
            self.assertTrue(entered.wait(5))
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and not list(deploy.glob('.*ctfd-part*')): time.sleep(0.02)
            self.assertTrue(list(deploy.glob('.*ctfd-part*')))
            child.kill(); child.communicate(timeout=5)
            self.assertEqual(child.returncode,-9)
        finally:
            if child.poll() is None: child.kill(); child.communicate(timeout=5)
            release.set()
        recovered=self.new_monitor()
        self.assertFalse(list(deploy.glob('.*ctfd-part*')))
        self.routes['/files/crash.bin']=(200,b'recovered',{})
        self.cycle(recovered)
        recovered.executor.shutdown(wait=True)
        self.assertEqual((deploy/'crash.bin').read_bytes(),b'recovered')
