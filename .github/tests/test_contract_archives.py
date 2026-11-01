import io
import stat
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from ctfd_monitor.archives import extract

class ArchiveContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_zip_duplicate_absolute_symlink_and_fifo(self):
        cases={
            'duplicate':[('same',b'a'),('same',b'b')],
            'absolute':[(str(self.root/'outside'),b'x')],
            'traversal':[('sub/../../outside',b'x')],
        }
        for name,files in cases.items():
            with self.subTest(name=name):
                archive=self.root/(name+'.zip')
                with warnings.catch_warnings(), zipfile.ZipFile(archive,'w') as z:
                    warnings.simplefilter('ignore',UserWarning)
                    for filename,data in files: z.writestr(filename,data)
                with self.assertRaises((ValueError,OSError)): extract(archive,self.root/name,100)
        for mode in (stat.S_IFLNK|0o777,stat.S_IFIFO|0o600):
            with self.subTest(mode=mode):
                archive=self.root/f'{mode}.zip'
                info=zipfile.ZipInfo('special'); info.create_system=3; info.external_attr=mode<<16
                with zipfile.ZipFile(archive,'w') as z: z.writestr(info,b'target')
                with self.assertRaises(ValueError): extract(archive,self.root/str(mode),100)

    def test_tar_normal_file_traversal_hardlink_and_device(self):
        for kind in ('normal','traversal','hardlink','device'):
            with self.subTest(kind=kind):
                archive=self.root/(kind+'.tar')
                with tarfile.open(archive,'w') as t:
                    info=tarfile.TarInfo('../escape' if kind=='traversal' else 'file')
                    if kind=='hardlink': info.type=tarfile.LNKTYPE; info.linkname='/etc/passwd'
                    elif kind=='device': info.type=tarfile.CHRTYPE
                    else: info.size=3
                    t.addfile(info,io.BytesIO(b'abc') if info.isfile() else None)
                if kind=='normal':
                    extract(archive,self.root/kind,10)
                    self.assertEqual((self.root/kind/'file').read_bytes(),b'abc')
                else:
                    with self.assertRaises(ValueError): extract(archive,self.root/kind,10)

    def test_total_bytes_limit_and_cancellation(self):
        archive=self.root/'data.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('a',b'123'); z.writestr('b',b'456')
        with self.assertRaises(ValueError): extract(archive,self.root/'limited',5)
        with self.assertRaises(RuntimeError): extract(archive,self.root/'cancelled',100,lambda:True)

    def test_archive_file_count_limit(self):
        archive=self.root/'many.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for i in range(10001): z.writestr(str(i),b'')
        with self.assertRaises(ValueError): extract(archive,self.root/'out',10)

    def test_corrupt_archive_fails(self):
        archive=self.root/'broken.zip'; archive.write_bytes(b'PK broken archive')
        with self.assertRaises((tarfile.TarError,zipfile.BadZipFile,ValueError)): extract(archive,self.root/'out',10)
