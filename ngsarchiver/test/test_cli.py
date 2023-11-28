# Unit tests for the 'cli' module

import unittest
import tempfile
import shutil
import os
import base64
from ngsarchiver.cli import CLIStatus
from ngsarchiver.cli import main

# Set to False to keep test output dirs
REMOVE_TEST_OUTPUTS = True

class UnittestDir:
    # Helper class for building test directories
    #
    # >>> d = UnittestDir('/path/to/dir')
    # >>> d.add('subdir',type='dir')
    # >>> d.add('subdir/a_file',type='file',content='stuff\n')
    # >>> d.add('a_symlink',type='symlink',target='subdir/a_file')
    # >>> d.add('a_link',type='link',target='subdir/a_file')
    # >>> d.create()
    #
    def __init__(self,p):
        # p is path to dir to be created (must not exist)
        self._p = os.path.abspath(p)
        self._contents = []
    @property
    def path(self):
        return self._p
    def add(self,p,type='file',content=None,target=None,mode=None):
        # p is path to content (relative to top-level)
        # type is one of 'file', 'dir', 'symlink', 'link', 'binary'
        # content is text to write to file
        # target is the target for links
        # mode is the permissions mode of the content
        self._contents.append(
            {
                'path': p,
                'type': type,
                'content': content,
                'target': target,
                'mode': mode,
            })
    def list(self,prefix=None):
        # Return list of (relative) paths
        paths = set()
        for c in self._contents:
            p = c['path']
            while p:
                if p not in paths:
                    if prefix:
                        paths.add(os.path.join(prefix,p))
                    else:
                        paths.add(p)
                p = os.path.dirname(p)
        return sorted(list(paths))
    def create(self,top_level=None):
        # Creates and populates the test directory
        # Directory will be created under initial path
        # unless 'top_level' dir is supplied when
        # 'create' is called
        if top_level is None:
            top_level = self.path
        print("Making dir '%s'" % top_level)
        os.mkdir(top_level)
        for c in self._contents:
            p = os.path.join(top_level,c['path'])
            type_ = c['type']
            print("...creating '%s' (%s)" % (p,type_))
            if type_ == 'dir':
                os.makedirs(p,exist_ok=True)
            elif type_ == 'file':
                os.makedirs(os.path.dirname(p),exist_ok=True)
                with open(p,'wt') as fp:
                    if c['content']:
                        fp.write(c['content'])
                    else:
                        fp.write('')
            elif type_ == 'binary':
                os.makedirs(os.path.dirname(p),exist_ok=True)
                with open(p,'wb') as fp:
                    fp.write(c['content'])
            elif type_ == 'symlink':
                os.makedirs(os.path.dirname(p),exist_ok=True)
                os.symlink(c['target'],p)
            elif type_ == 'link':
                os.makedirs(os.path.dirname(p),exist_ok=True)
                os.link(c['target'],p)
            else:
                print("Unknown type '%s'" % c['type'])
                continue
            if c['mode']:
                os.chmod(p,c['mode'])

class TestCLI(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestCLI')
        self.starting_dir = os.getcwd()
        os.chdir(self.wd)

    def tearDown(self):
        os.chdir(self.starting_dir)
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_help(self):
        """
        CLI: test the -h option
        """
        self.assertRaises(SystemExit,
                          main,
                          ['-h'])

    def test_version(self):
        """
        CLI: test the --version option
        """
        self.assertRaises(SystemExit,
                          main,
                          ['--version'])

    def test_info(self):
        """
        CLI: test the 'info' command
        """
        # Empty directory
        self.assertEqual(main(['info',self.wd]),0)
        # Non-empty directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.create()
        self.assertEqual(main(['info',example_dir.path]),
                         CLIStatus.OK)

    def test_archive(self):
        """
        CLI: test the 'archive' command
        """
        # Make example directory to archive
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.create()
        self.assertEqual(main(['archive',example_dir.path]),
                         CLIStatus.OK)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example.archive")))

    def test_archive_already_exists(self):
        """
        CLI: test the 'archive' command (archive directory already present)
        """
        # Make example directory to archive
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.create()
        # Creat placeholder archive directory
        os.mkdir(os.path.join(self.wd,"example.archive"))
        self.assertEqual(main(['archive',example_dir.path]),
                         CLIStatus.ERROR)

    def test_verify(self):
        """
        CLI: test the 'verify' command
        """
        # Make example archive dir to verify
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archive"))
        example_archive.add("example.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+2ZYWqDQBCF/Z1TeIJkdxzda/QKpllog6HBbMDjd7QVopKWQJxt2ff9MehCFl6+8Wl8V5/Ojd9lK2IE58r+aF1pbo8jmWXmQpZZI+usqchmebnmpkaul1C3eZ6dj/sf1/12/Z/iv/O/XPeH95ZW+R08lL+T85bkOvLXYJ6/72gbuvDU7+gDriq+n7/IPs2/YJL8zVN3cYfE839p6lf/9tEcfJsH34VN7A0BVZb+27/hP8N/DeB/2kz9t/H7H1df/c+h/2kwzz96/xvyl/nvMP81wPxPm6X/kfsfM/qfIvA/bab+F/H7n6O+/5GcQv9TYJ5/9P435F/IZ8x/DTD/02bpf+z3f4TnP0Xgf9qM/q/h/chD/g///5Mpcf9XAf4DAECafAIvyELwACgAAA=='))
        example_archive.add("example.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex1.txt
""")
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content="f210d02b4a294ec38c6ed82b92a73c44  example.tar.gz\n")
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "subarchives": [
    "example.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add(".ngsarchiver/manifest.txt",type="file")
        example_archive.create()
        self.assertEqual(main(['verify',example_archive.path]),
                         CLIStatus.OK)

    def test_unpack(self):
        """
        CLI: test the 'unpack' command
        """
        # Make example archive dir to unpack
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archive"))
        example_archive.add("example.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+2ZYWqDQBCF/Z1TeIJkdxzda/QKpllog6HBbMDjd7QVopKWQJxt2ff9MehCFl6+8Wl8V5/Ojd9lK2IE58r+aF1pbo8jmWXmQpZZI+usqchmebnmpkaul1C3eZ6dj/sf1/12/Z/iv/O/XPeH95ZW+R08lL+T85bkOvLXYJ6/72gbuvDU7+gDriq+n7/IPs2/YJL8zVN3cYfE839p6lf/9tEcfJsH34VN7A0BVZb+27/hP8N/DeB/2kz9t/H7H1df/c+h/2kwzz96/xvyl/nvMP81wPxPm6X/kfsfM/qfIvA/bab+F/H7n6O+/5GcQv9TYJ5/9P435F/IZ8x/DTD/02bpf+z3f4TnP0Xgf9qM/q/h/chD/g///5Mpcf9XAf4DAECafAIvyELwACgAAA=='))
        example_archive.add("example.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex1.txt
""")
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content="f210d02b4a294ec38c6ed82b92a73c44  example.tar.gz\n")
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "subarchives": [
    "example.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add(".ngsarchiver/manifest.txt",type="file")
        example_archive.create()
        self.assertEqual(main(['unpack',example_archive.path]),
                         CLIStatus.OK)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))

    def test_compare(self):
        """
        CLI: test the 'compare' command
        """
        # Make example directories to compare
        example_dir1 = UnittestDir(os.path.join(self.wd,"example1"))
        example_dir1.add("ex1.txt",type="file",content="example 1")
        example_dir1.add("subdir1/ex2.txt",type="file")
        example_dir1.create()
        example_dir2 = UnittestDir(os.path.join(self.wd,"example2"))
        example_dir2.add("ex1.txt",type="file",content="example 1")
        example_dir2.add("subdir1/ex2.txt",type="file")
        example_dir2.create()
        example_dir3 = UnittestDir(os.path.join(self.wd,"example3"))
        example_dir3.add("ex1.txt",type="file",content="example 3")
        example_dir3.add("subdir1/ex2.txt",type="file")
        example_dir3.create()
        example_dir4 = UnittestDir(os.path.join(self.wd,"example4"))
        example_dir4.add("ex1.txt",type="file",content="example 1")
        example_dir4.add("ex3.txt",type="file",content="example 3")
        example_dir4.add("subdir1/ex2.txt",type="file")
        example_dir4.create()
        self.assertEqual(main(['compare',
                               example_dir1.path,
                               example_dir2.path]),
                         CLIStatus.OK)
        self.assertEqual(main(['compare',
                               example_dir2.path,
                               example_dir1.path]),
                         CLIStatus.OK)
        self.assertEqual(main(['compare',
                               example_dir1.path,
                               example_dir3.path]),
                         CLIStatus.ERROR)
        self.assertEqual(main(['compare',
                               example_dir1.path,
                               example_dir4.path]),
                         CLIStatus.ERROR)

    def test_search(self):
        """
        CLI: test the 'search' command
        """
        # Make example archive dir to search
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archive"))
        example_archive.add("example.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+2ZYWqDQBCF/Z1TeIJkdxzda/QKpllog6HBbMDjd7QVopKWQJxt2ff9MehCFl6+8Wl8V5/Ojd9lK2IE58r+aF1pbo8jmWXmQpZZI+usqchmebnmpkaul1C3eZ6dj/sf1/12/Z/iv/O/XPeH95ZW+R08lL+T85bkOvLXYJ6/72gbuvDU7+gDriq+n7/IPs2/YJL8zVN3cYfE839p6lf/9tEcfJsH34VN7A0BVZb+27/hP8N/DeB/2kz9t/H7H1df/c+h/2kwzz96/xvyl/nvMP81wPxPm6X/kfsfM/qfIvA/bab+F/H7n6O+/5GcQv9TYJ5/9P435F/IZ8x/DTD/02bpf+z3f4TnP0Xgf9qM/q/h/chD/g///5Mpcf9XAf4DAECafAIvyELwACgAAA=='))
        example_archive.add("example.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex1.txt
""")
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content="f210d02b4a294ec38c6ed82b92a73c44  example.tar.gz\n")
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "subarchives": [
    "example.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add(".ngsarchiver/manifest.txt",type="file")
        example_archive.create()
        self.assertEqual(main(['search',
                               '-name','ex*.txt',
                               example_archive.path]),
                         CLIStatus.OK)

    def test_extract(self):
        """
        CLI: test the 'search' command
        """
        # Make example archive dir to extract files from
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archive"))
        example_archive.add("example.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+2ZYWqDQBCF/Z1TeIJkdxzda/QKpllog6HBbMDjd7QVopKWQJxt2ff9MehCFl6+8Wl8V5/Ojd9lK2IE58r+aF1pbo8jmWXmQpZZI+usqchmebnmpkaul1C3eZ6dj/sf1/12/Z/iv/O/XPeH95ZW+R08lL+T85bkOvLXYJ6/72gbuvDU7+gDriq+n7/IPs2/YJL8zVN3cYfE839p6lf/9tEcfJsH34VN7A0BVZb+27/hP8N/DeB/2kz9t/H7H1df/c+h/2kwzz96/xvyl/nvMP81wPxPm6X/kfsfM/qfIvA/bab+F/H7n6O+/5GcQv9TYJ5/9P435F/IZ8x/DTD/02bpf+z3f4TnP0Xgf9qM/q/h/chD/g///5Mpcf9XAf4DAECafAIvyELwACgAAA=='))
        example_archive.add("example.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex1.txt
""")
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content="f210d02b4a294ec38c6ed82b92a73c44  example.tar.gz\n")
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "subarchives": [
    "example.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add(".ngsarchiver/manifest.txt",type="file")
        example_archive.create()
        self.assertEqual(main(['extract',
                               '-name','*subdir1/ex1*.txt',
                               example_archive.path]),
                         CLIStatus.OK)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"ex1.txt")))