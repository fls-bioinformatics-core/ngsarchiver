# Unit tests for the 'archive' module

import os
import pwd
import grp
import unittest
import tempfile
import tarfile
import random
import string
import shutil
import base64
import getpass
from ngsarchiver.archive import Directory
from ngsarchiver.archive import GenericRun
from ngsarchiver.archive import MultiSubdirRun
from ngsarchiver.archive import MultiProjectRun
from ngsarchiver.archive import ArchiveDirectory
from ngsarchiver.archive import ArchiveDirMember
from ngsarchiver.archive import get_rundir_instance
from ngsarchiver.archive import md5sum
from ngsarchiver.archive import verify_checksums
from ngsarchiver.archive import make_archive_dir
from ngsarchiver.archive import make_archive_tgz
from ngsarchiver.archive import make_archive_multitgz
from ngsarchiver.archive import unpack_archive_multitgz
from ngsarchiver.archive import getsize
from ngsarchiver.archive import convert_size_to_bytes
from ngsarchiver.archive import format_size
from ngsarchiver.exceptions import NgsArchiverException

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
    def add_batch(self,paths,type='file',content=None,target=None,
                  mode=None):
        # Add multiple paths with same type, content etc
        for p in paths:
            self.add(p,type=type,content=content,target=target,
                     mode=mode)
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

def random_text(n):
    # Return random ASCII text consisting of
    # n characters
    return ''.join(random.choice(string.ascii_lowercase) for i in range(n))

class TestDirectory(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestDirectory')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)
    
    def test_directory_properties(self):
        """
        Directory: check basic properties
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Check properties
        d = Directory(p)
        self.assertEqual(repr(d),p)
        self.assertEqual(d.path,p)
        self.assertEqual(d.basename,"example")
        self.assertEqual(d.parent_dir,self.wd)
        self.assertEqual(d.size,8192)
        self.assertEqual(list(d.compressed_files),[])
        self.assertEqual(list(d.unknown_uids),[])
        self.assertFalse(d.has_unknown_uids)

    def test_directory_getsize(self):
        """
        Directory: check 'getsize' method
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Check getsize method
        d = Directory(p)
        file_list = [os.path.join(p,f) for f in ("ex1.txt",)]
        self.assertEqual(d.getsize(file_list),4096)

    def test_directory_external_symlinks(self):
        """
        Directory: check handling of external symlinks
        """
        # Build example dir without external symlinks
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./ext.txt")
        example_dir.create()
        p = example_dir.path
        # No external symlinks should be detected
        d = Directory(p)
        self.assertEqual(list(d.external_symlinks),[])
        self.assertFalse(d.has_external_symlinks)
        # Add symlink to external file
        external_file = os.path.join(self.wd,"external")
        with open(external_file,'wt') as fp:
            fp.write("external content")
        external_symlink = os.path.join(p,"symlink2")
        os.symlink("../external",external_symlink)
        # External symlink should be detected
        self.assertEqual(list(d.external_symlinks),[external_symlink,])
        self.assertTrue(d.has_external_symlinks)

    def test_directory_broken_symlinks(self):
        """
        Directory: check handling of broken symlinks
        """
        # Build example dir without external symlinks
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./ex1.txt")
        example_dir.create()
        p = example_dir.path
        # No broken symlinks should be detected and unknown
        # UID detection should function correctly
        d = Directory(p)
        self.assertEqual(list(d.broken_symlinks),[])
        self.assertFalse(d.has_broken_symlinks)
        self.assertEqual(list(d.unknown_uids),[])
        self.assertFalse(d.has_unknown_uids)
        # Add broken symlink
        broken_symlink = os.path.join(p,"broken")
        os.symlink("./missing.txt",broken_symlink)
        # External symlink should be detected and unknown
        # UID detection should function correctly
        self.assertEqual(list(d.broken_symlinks),[broken_symlink,])
        self.assertTrue(d.has_broken_symlinks)
        self.assertEqual(list(d.unknown_uids),[])
        self.assertFalse(d.has_unknown_uids)

    def test_directory_readability(self):
        """
        Directory: check readability
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Check readability
        d = Directory(p)
        self.assertEqual(list(d.unreadable_files),[])
        self.assertTrue(d.is_readable)
        # Make unreadable file by stripping permissions
        unreadable_file = os.path.join(p,"ex1.txt")
        os.chmod(unreadable_file,0o266)
        self.assertEqual(list(d.unreadable_files),[unreadable_file,])
        self.assertFalse(d.is_readable)

    def test_directory_writeability(self):
        """
        Directory: check writeability
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Check writability
        d = Directory(p)
        self.assertTrue(d.is_writeable)
        # Make unwriteable file by stripping permissions
        unwriteable_file = os.path.join(p,"ex1.txt")
        os.chmod(unwriteable_file,0o466)
        self.assertFalse(d.is_writeable)

    def test_directory_hard_links(self):
        """
        Directory: check handling of hard links
        """
        # Build example dir without hard links
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("ex2.txt",type="file",content="example 2")
        example_dir.create()
        p = example_dir.path
        # No hard links should be detected
        d = Directory(p)
        self.assertEqual(list(d.hard_linked_files),[])
        self.assertFalse(d.has_hard_linked_files)
        # Add hard link
        hard_link_src = os.path.join(p,"ex1.txt")
        hard_link_dst = os.path.join(p,"ex12.txt")
        os.link(hard_link_src,hard_link_dst)
        # External symlink should be detected
        self.assertEqual(sorted(list(d.hard_linked_files)),
                         sorted([hard_link_src,hard_link_dst]))
        self.assertTrue(d.has_hard_linked_files)

    def test_directory_check_group(self):
        """
        Directory: check 'check_group' method
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Get info on UID, GIDs etc
        user = getpass.getuser()
        primary_group = grp.getgrgid(pwd.getpwnam(user).pw_gid).gr_name
        # Check group
        d = Directory(p)
        self.assertTrue(d.check_group(primary_group))
        # Other groups for current user
        other_groups = [grp.getgrgid(g).gr_name for g in os.getgroups()]
        other_groups.remove(primary_group)
        for g in other_groups:
            self.assertFalse(d.check_group(g))

    def test_directory_verify_copy(self):
        """
        Directory: check 'verify_copy' method
        """
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        dir1 = os.path.join(os.path.join(self.wd,"example1"))
        example_dir.create(dir1)
        dir2 = os.path.join(os.path.join(self.wd,"example2"))
        example_dir.create(dir2)
        # Check verification when identical
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertTrue(d1.verify_copy(dir2))
        self.assertTrue(d2.verify_copy(dir1))
        # Add a file to second directory
        with open(os.path.join(dir2,"extra.txt"),'wt') as fp:
            fp.write("extra stuff")
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))

    def test_directory_chown(self):
        """
        Directory: check 'chown' method
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Get info on UID, GIDs etc
        user = getpass.getuser()
        primary_group = grp.getgrgid(pwd.getpwnam(user).pw_gid).gr_name
        # Other groups for current user
        other_groups = [grp.getgrgid(g).gr_name for g in os.getgroups()]
        other_groups.remove(primary_group)
        if other_groups:
            # Check primary group
            d = Directory(p)
            self.assertTrue(d.check_group(primary_group))
            # Select an alternative group
            other_group = other_groups[0]
            # Change to alternative using chown
            d.chown(group=other_group)
            self.assertTrue(d.check_group(other_group))
        else:
            # No alternatives available
            self.skipTest("no alternative groups available")

    def test_directory_walk(self):
        """
        Directory: check 'walk' method
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Check walk method
        d = Directory(p)
        self.assertEqual(list(d.walk()),
                         [os.path.join(p,f)
                          for f in ("ex1.txt",
                                    "subdir1",
                                    "subdir1/ex2.txt",
                                    "subdir1/subdir12",
                                    "subdir1/subdir12/ex3.txt")])

class TestGenericRun(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestGenericRun')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_genericrun(self):
        """
        GenericRun: check archive creation
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir2/ex3.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Create instance and create an archive directory
        d = GenericRun(p)
        a = d.make_archive(out_dir=self.wd)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        self.assertEqual(a.path,os.path.join(self.wd,"example.archive"))
        self.assertTrue(os.path.exists(a.path))
        self.assertTrue(os.path.exists(os.path.join(a.path,
                                                    "example.tar.gz")))

class TestMultiSubdirRun(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMultiSubdirRun')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_multisubdirrun(self):
        """
        MultiSubdirRun: check archive creation
        """
        # Build example multi-subdir directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("Project1/README",type="file")
        for ix,sample in enumerate(("EX1","EX2")):
            for read in ("R1","R2"):
                example_dir.add("Project1/fastqs/%s_S%d_L1_%s_001.fastq"
                                % (sample,ix,read),type="file")
        example_dir.add("Project2/README",type="file")
        for ix,sample in enumerate(("EX3","EX4")):
            for read in ("R1","R2"):
                example_dir.add("Project2/fastqs/%s_S%d_L1_%s_001.fastq"
                                % (sample,ix,read),type="file")
        example_dir.add("bcl2fastq/README",type="file")
        example_dir.create()
        p = example_dir.path
        # Create instance and create an archive directory
        d = MultiSubdirRun(p)
        a = d.make_archive(out_dir=self.wd)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        self.assertEqual(a.path,os.path.join(self.wd,"example.archive"))
        self.assertTrue(os.path.exists(a.path))
        for name in ("Project1.tar.gz",
                     "Project2.tar.gz",
                     "bcl2fastq.tar.gz"):
            self.assertTrue(os.path.exists(os.path.join(a.path,name)))

class TestMultiProjectRun(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMultiProjectRun')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_multiprojectrun(self):
        """
        MultiProjectRun: check properties and archive creation
        """
        # Build example multi-project dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("projects.info",type="file",
                        content="#Header\nProject1\tsome\tstuff\nProject2\tmore\tstuff\n")
        example_dir.add("Project1/README",type="file")
        for ix,sample in enumerate(("EX1","EX2")):
            for read in ("R1","R2"):
                example_dir.add("Project1/fastqs/%s_S%d_L1_%s_001.fastq"
                                % (sample,ix,read),type="file")
        example_dir.add("Project2/README",type="file")
        for ix,sample in enumerate(("EX3","EX4")):
            for read in ("R1","R2"):
                example_dir.add("Project2/fastqs/%s_S%d_L1_%s_001.fastq"
                                % (sample,ix,read),type="file")
        example_dir.add("undetermined/README",type="file")
        for read in ("R1","R2"):
            example_dir.add("undetermined/fastqs/"
                            "Undetermined_S0_L1_%s_001.fastq" % read,
                            type="file")
        example_dir.add("processing_qc.html",type="file")
        example_dir.add("barcodes/barcode_report.html",type="file")
        example_dir.add("statistics.info",type="file")
        example_dir.add("auto_process.info",type="file")
        example_dir.add("metadata.info",type="file")
        example_dir.add("SampleSheet.csv",type="file")
        example_dir.create()
        p = example_dir.path
        # Create instance and check properties
        d = MultiProjectRun(p)
        self.assertEqual(d.project_dirs,["Project1",
                                         "Project2",
                                         "undetermined"])
        self.assertEqual(d.processing_artefacts,
                         ["SampleSheet.csv",
                          "auto_process.info",
                          "barcodes",
                          "metadata.info",
                          "processing_qc.html",
                          "statistics.info"])
        # Create an archive directory
        a = d.make_archive(out_dir=self.wd)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        self.assertEqual(a.path,os.path.join(self.wd,"example.archive"))
        self.assertTrue(os.path.exists(a.path))
        for name in ("Project1.tar.gz",
                     "Project2.tar.gz",
                     "undetermined.tar.gz",
                     "processing.tar.gz",
                     "projects.info"):
            self.assertTrue(os.path.exists(os.path.join(a.path,name)))

class TestArchiveDirectory(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestArchiveDirectory')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_archivedirectory_single_subarchive(self):
        """
        ArchiveDirectory: single subarchive
        """
        # Build example archive dir
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
        p = example_archive.path
        # Expected contents
        expected = ('example/ex1.txt',
                    'example/subdir1',
                    'example/subdir1/ex1.txt',
                    'example/subdir1/ex2.txt',
                    'example/subdir2',
                    'example/subdir2/ex1.txt',
                    'example/subdir2/ex2.txt',
                    'example/subdir3',
                    'example/subdir3/ex1.txt',
                    'example/subdir3/ex2.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example")
        self.assertEqual(metadata['subarchives'],["example.tar.gz"])
        self.assertEqual(metadata['files'],[])
        self.assertEqual(metadata['multi_volume'],False)
        self.assertEqual(metadata['volume_size'],None)
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)

    def test_archivedirectory_multiple_subarchives(self):
        """
        ArchiveDirectory: multiple subarchives
        """
        # Build example archive dir
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archive"))
        example_archive.add("subdir1.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+3T3QqCMBjG8R13FV5BbnO62+gWNAcVRqILdvkpEYRhnfiB9P+dvAd7YS88PC7k17pycXsvynOjYjED2bE27aeyqXyfL0IZY5JuTZlMSKWVtSJK5zhm6N76vIkiUV+Kr3u/3jfKDfJ3Qe998JP+0QecZWY8f60G+SdGd/nLSa8Y8ef5H6r86E63qnRN5F3wu7UPwqI++69W7r959t/Q/yXQfwAAAAAAAAAAAAAAtu8BVJJOSAAoAAA='))
        example_archive.add("subdir1.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex1.txt
""")
        example_archive.add("subdir2.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+3T0QqCMBTG8V33FHuCdHO61+gVNAcVRqITfPzmRRCGdaOW9P/dHNg5sAMfx/X5ta5c1HZFeW50JBYQB9amQ1U2jZ/rg1DGmCSMKRvelQ59IdMllhnrWp83Uor6Uryd+9TfKDfK3/V673s/6x9DwFlmpvPXapR/YnTIP551iwl/nv+hyo/udKtK10jver/79kJY1ev9q9+4f8P9r4H7BwAAAAAAAAAAAABg++79kqV0ACgAAA=='))
        example_archive.add("subdir2.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex1.txt
""")
        example_archive.add("miscellaneous.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+3W0QrCIBQGYK97Cp+gHZ3O1+gVtiZULBqbAx8/V0GxqCjmovZ/N4oOdkD+o9bn+7qyifVi6bxjMVCQZaofhdF0O55JwYRSKiUygjQjISlsc4pSzUDXurzhnNW74ul3r/Z/1KrK13ZzqErbcGe9W3y7IJiUveS/7Ypy26RJjH/0ETdGP84/0TX/Rvb5l2GJ6xjFDM08/8Pzt16Ofg+81f9P55+GOfr/FND/5+0+/+O/Az/JvzTI/xSQfwAAAAAAAAAAAAAAAID/cQRHXCooACgAAA=='))
        example_archive.add("miscellaneous.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex1.txt
""")
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content="""ea40b4706e9d97459173ddba2cc8f673  subdir1.tar.gz
21ab03a93bb341292ca281bf7f9d7176  subdir2.tar.gz
a0b67a19eabb5b96f97a8694e4d8cd9e  miscellaneous.tar.gz
""")
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "subarchives": [
    "subdir1.tar.gz",
    "subdir2.tar.gz",
    "miscellaneous.tar.gz"
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
        p = example_archive.path
        # Expected contents
        expected = ('example/ex1.txt',
                    'example/subdir1',
                    'example/subdir1/ex1.txt',
                    'example/subdir1/ex2.txt',
                    'example/subdir2',
                    'example/subdir2/ex1.txt',
                    'example/subdir2/ex2.txt',
                    'example/subdir3',
                    'example/subdir3/ex1.txt',
                    'example/subdir3/ex2.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example")
        self.assertEqual(metadata['subarchives'],["subdir1.tar.gz",
                                                  "subdir2.tar.gz",
                                                  "miscellaneous.tar.gz"])
        self.assertEqual(metadata['files'],[])
        self.assertEqual(metadata['multi_volume'],False)
        self.assertEqual(metadata['volume_size'],None)
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)

    def test_archivedirectory_multiple_subarchives_and_file(self):
        """
        ArchiveDirectory: multiple subarchives and extra file
        """
        # Build example archive dir
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archive"))
        example_archive.add("extra_file.txt",
                            type="file",
                            content="Extra stuff\n")
        example_archive.add("subdir1.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+3T3QqCMBjG8R13FV5BbnO62+gWNAcVRqILdvkpEYRhnfiB9P+dvAd7YS88PC7k17pycXsvynOjYjED2bE27aeyqXyfL0IZY5JuTZlMSKWVtSJK5zhm6N76vIkiUV+Kr3u/3jfKDfJ3Qe998JP+0QecZWY8f60G+SdGd/nLSa8Y8ef5H6r86E63qnRN5F3wu7UPwqI++69W7r959t/Q/yXQfwAAAAAAAAAAAAAAtu8BVJJOSAAoAAA='))
        example_archive.add("subdir1.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir1/ex1.txt
""")
        example_archive.add("subdir2.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+3T0QqCMBTG8V33FHuCdHO61+gVNAcVRqITfPzmRRCGdaOW9P/dHNg5sAMfx/X5ta5c1HZFeW50JBYQB9amQ1U2jZ/rg1DGmCSMKRvelQ59IdMllhnrWp83Uor6Uryd+9TfKDfK3/V673s/6x9DwFlmpvPXapR/YnTIP551iwl/nv+hyo/udKtK10jver/79kJY1ev9q9+4f8P9r4H7BwAAAAAAAAAAAABg++79kqV0ACgAAA=='))
        example_archive.add("subdir2.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir2/ex1.txt
""")
        example_archive.add("miscellaneous.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sIAAAAAAAAA+3W0QrCIBQGYK97Cp+gHZ3O1+gVtiZULBqbAx8/V0GxqCjmovZ/N4oOdkD+o9bn+7qyifVi6bxjMVCQZaofhdF0O55JwYRSKiUygjQjISlsc4pSzUDXurzhnNW74ul3r/Z/1KrK13ZzqErbcGe9W3y7IJiUveS/7Ypy26RJjH/0ETdGP84/0TX/Rvb5l2GJ6xjFDM08/8Pzt16Ofg+81f9P55+GOfr/FND/5+0+/+O/Az/JvzTI/xSQfwAAAAAAAAAAAAAAAID/cQRHXCooACgAAA=='))
        example_archive.add("miscellaneous.md5",
                            type="file",
                            content="""d1ee10b76e42d7e06921e41fbb9b75f7  example/ex1.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex2.txt
d1ee10b76e42d7e06921e41fbb9b75f7  example/subdir3/ex1.txt
""")
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content="""f299d91fe1d73319e4daa11dc3a12a33  extra_file.txt
ea40b4706e9d97459173ddba2cc8f673  subdir1.tar.gz
21ab03a93bb341292ca281bf7f9d7176  subdir2.tar.gz
a0b67a19eabb5b96f97a8694e4d8cd9e  miscellaneous.tar.gz
""")
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "subarchives": [
    "subdir1.tar.gz",
    "subdir2.tar.gz",
    "miscellaneous.tar.gz"
  ],
  "files": [
    "extra_file.txt"
  ],
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
        p = example_archive.path
        # Expected contents
        expected = ('example/extra_file.txt',
                    'example/ex1.txt',
                    'example/subdir1',
                    'example/subdir1/ex1.txt',
                    'example/subdir1/ex2.txt',
                    'example/subdir2',
                    'example/subdir2/ex1.txt',
                    'example/subdir2/ex2.txt',
                    'example/subdir3',
                    'example/subdir3/ex1.txt',
                    'example/subdir3/ex2.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example")
        self.assertEqual(metadata['subarchives'],["subdir1.tar.gz",
                                                  "subdir2.tar.gz",
                                                  "miscellaneous.tar.gz"])
        self.assertEqual(metadata['files'],["extra_file.txt"])
        self.assertEqual(metadata['multi_volume'],False)
        self.assertEqual(metadata['volume_size'],None)
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)

    def test_archivedirectory_multi_volume_single_subarchive(self):
        """
        ArchiveDirectory: single multi-volume subarchive
        """
        # Define archive dir contents
        MULTI_VOLUME_SINGLE_SUBARCHIVE = {
            "example.00": {
                "b64": b'H4sIAAAAAAAAA+3OTQrCMBCG4aw9RU5gJ+3YXsMrpDagErGkKeT4Vty48WdREOF9Nu9iZvGF4i9jDNU098MpuSoUt80lmzXJom31Xtft5LkPtTNOVRuRbqkR12itxsqqK16Yp+yTtWY892//Pt3/1D76Qzhe4xCSzaHkza8HAQAAAAAAAAAAAAAAAAC+cgOMxjgDACgAAA==',
                "contents": [
                    ("example/subdir1/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "1008e36e3235a2bd82ddbb7bf68e7767"
            },
            "example.01": {
                "b64": b'H4sIAAAAAAAAA+3OSwrCMBSF4YxdRVZgkzQ223ALqb2gErGkKWT5Vpw48TEoiPB/kwP33MGRGi9jkmaa++GUXSPVbkstak1m0XX+njbszHM+OKus9741Jtiw3G3rnVfarLrihXkqMWutxnP/9u9T/6f2KR7keE2DZF2kls2vBwEAAAAAAAAAAAAAAAAAvnIDTYFecAAoAAA=',
                "contents": [
                    ("example/subdir2/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "aa1e47917b73e55ce84fbf5abbadac9c"
            }
        }
        # Build example archive dir
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archive"))
        md5s = []
        for name in MULTI_VOLUME_SINGLE_SUBARCHIVE:
            data = MULTI_VOLUME_SINGLE_SUBARCHIVE[name]
            # Tar.gz file for subarchive
            example_archive.add("%s.tar.gz" % name,
                                type="binary",
                                content=base64.b64decode(data['b64']))
            # MD5 file for contents
            example_archive.add("%s.md5" % name,
                                type="file",
                                content='\n'.join(["%s  %s" %
                                                   (d[1],d[0])
                                                   for d in data['contents']]))
            # Store archive MD5
            md5s.append(("%s.tar.gz" % name,data['md5']))
        # MD5 for archive dir
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content='\n'.join(["%s  %s" % (m[1],m[0])
                                               for m in md5s]))
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "subarchives": [
    "example.00.tar.gz",
    "example.01.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "23-06-16 09:58:39",
  "multi_volume": true,
  "volume_size": "250M",
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add(".ngsarchiver/manifest.txt",type="file")
        example_archive.create()
        p = example_archive.path
        # Expected contents
        expected = ('example/subdir1',
                    'example/subdir1/ex1.txt',
                    'example/subdir2',
                    'example/subdir2/ex1.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example")
        self.assertEqual(metadata['subarchives'],["example.00.tar.gz",
                                                  "example.01.tar.gz"])
        self.assertEqual(metadata['files'],[])
        self.assertEqual(metadata['multi_volume'],True)
        self.assertEqual(metadata['volume_size'],"250M")
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)

    def test_archivedirectory_multi_volume_multiple_subarchives(self):
        """
        ArchiveDirectory: multiple multi-volume subarchives
        """
        # Define archive dir contents
        MULTI_VOLUME_MULTIPLE_SUBARCHIVES = {
            "subdir1.00": {
                "b64": b'H4sIAAAAAAAAA+3OTQrCMBCG4aw9RU5gJ+3YXsMrpDagErGkKeT4Vty48WdREOF9Nu9iZvGF4i9jDNU098MpuSoUt80lmzXJom31Xtft5LkPtTNOVRuRbqkR12itxsqqK16Yp+yTtWY892//Pt3/1D76Qzhe4xCSzaHkza8HAQAAAAAAAAAAAAAAAAC+cgOMxjgDACgAAA==',
                "contents": [
                    ("example/subdir1/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "1008e36e3235a2bd82ddbb7bf68e7767"
            },
            "subdir1.01": {
                "b64": b'H4sIAAAAAAAAA+3OTQrCMBiE4aw9RU5gk/QzuYZXaG1AJWJJU8jxq7hx48+iIML7bGYxs5hYu8uYYjPN/XDKtonVbUstak3mxnu5pw0785wPziorIq0xwYpXxrbigtJm1RcvzFPpstZqPPdvd5/6P7VP3SEer2mIWZdYy+bXhwAAAAAAAAAAAAAAAAAAX1kA/Ab9xAAoAAA=',
                "contents": [
                    ("example/subdir1/ex2.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "df145dac88a341d59709395361ddcb0c"
            },
            "subdir2.00": {
                "b64": b'H4sIAAAAAAAAA+3OSwrCMBSF4YxdRVZgkzQ223ALqb2gErGkKWT5Vpw48TEoiPB/kwP33MGRGi9jkmaa++GUXSPVbkstak1m0XX+njbszHM+OKus9741Jtiw3G3rnVfarLrihXkqMWutxnP/9u9T/6f2KR7keE2DZF2kls2vBwEAAAAAAAAAAAAAAAAAvnIDTYFecAAoAAA=',
                "contents": [
                    ("example/subdir2/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "aa1e47917b73e55ce84fbf5abbadac9c"
            },
            "subdir2.01": {
                "b64": b'H4sIAAAAAAAAA+3OSwrCMBSF4YxdRVZgkzRttuEWWntBJWJJU8jyW3HixMegIML/TQ7ccwdHSncdo1TT3A/n5Copbp9LVlsyq7b197ShMc/54Kyy3vvamGDDere1d43SZtMVL8xT7pLWarz0b/8+9X/qELujnG5xkKSzlLz79SAAAAAAAAAAAAAAAAAAwFcWnpOniAAoAAA=',
                "contents": [
                    ("example/subdir2/ex2.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "35f2b1326ed67ab2661d7a0aa1a1c277"
            },
            "miscellaneous.00": {
                "b64": b'H4sIAAAAAAAAA+3OMQrCQBSE4a09xZ5A34ub5BpeYdUHIiuG+IQ9vhEbsVCbIML/NVPMFGM1n4ZiK6u69OphDjLpunRP7Vt5zodGg6aU1iK9ShtEG5nqKLO8eXG9eB5jDMNx+3b3qf9Tm5J3djiXvY3Rrfri14cAAAAAAAAAAAAAAAAAAF+5AWYSJbwAKAAA',
                "contents": [
                    ("example/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "3c28749fd786eb199e6c2d20e224f7c9"
            },
            "miscellaneous.01": {
                "b64": b'H4sIAAAAAAAAA+3TOw6CQBSF4aldxaxA5iWzDbcAchM1GAkMySwfjY2JURuCkvxfc4p7i9McydWla6UYxro59b6QbLcpJzUnc1OW4Z427sxzPjirbAjBGxNtdMpYH1xU2sza4o1xSFWvterO9ce/b/eV2rfVQY7XtpFeJ8lp8+tCWJS87N/9xf69Yf9LYP8AAAAAAAAAAAAAAADrNgFkm3NNACgAAA==',
                "contents": [
                    ("example/subdir3/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7"),
                    ("example/subdir3/ex2.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "6bb7bf22c1dd5b938c431c6696eb6af9"
            }
        }
        # Build example archive dir
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archive"))
        md5s = []
        for name in MULTI_VOLUME_MULTIPLE_SUBARCHIVES:
            data = MULTI_VOLUME_MULTIPLE_SUBARCHIVES[name]
            # Tar.gz file for subarchive
            example_archive.add("%s.tar.gz" % name,
                                type="binary",
                                content=base64.b64decode(data['b64']))
            # MD5 file for contents
            example_archive.add("%s.md5" % name,
                                type="file",
                                content='\n'.join(["%s  %s" %
                                                   (d[1],d[0])
                                                   for d in data['contents']]))
            # Store archive MD5
            md5s.append(("%s.tar.gz" % name,data['md5']))
        # MD5 for archive dir
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content='\n'.join(["%s  %s" % (m[1],m[0])
                                               for m in md5s]))
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "subarchives": [
    "subdir1.00.tar.gz",
    "subdir1.01.tar.gz",
    "subdir2.00.tar.gz",
    "subdir2.01.tar.gz",
    "miscellaneous.00.tar.gz",
    "miscellaneous.01.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "23-06-16 09:58:39",
  "multi_volume": true,
  "volume_size": "250M",
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add(".ngsarchiver/manifest.txt",type="file")
        example_archive.create()
        p = example_archive.path
        # Expected contents
        expected = ('example/ex1.txt',
                    'example/subdir1',
                    'example/subdir1/ex1.txt',
                    'example/subdir1/ex2.txt',
                    'example/subdir2',
                    'example/subdir2/ex1.txt',
                    'example/subdir2/ex2.txt',
                    'example/subdir3',
                    'example/subdir3/ex1.txt',
                    'example/subdir3/ex2.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example")
        self.assertEqual(metadata['subarchives'],["subdir1.00.tar.gz",
                                                  "subdir1.01.tar.gz",
                                                  "subdir2.00.tar.gz",
                                                  "subdir2.01.tar.gz",
                                                  "miscellaneous.00.tar.gz",
                                                  "miscellaneous.01.tar.gz"])
        self.assertEqual(metadata['files'],[])
        self.assertEqual(metadata['multi_volume'],True)
        self.assertEqual(metadata['volume_size'],"250M")
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)

    def test_archivedirectory_multi_volume_multiple_subarchives_and_file(self):
        """
        ArchiveDirectory: multiple multi-volume subarchives and extra file
        """
        # Define archive dir contents
        MULTI_VOLUME_MULTIPLE_SUBARCHIVES_AND_FILE = {
            "subdir1.00": {
                "b64": b'H4sIAAAAAAAAA+3OTQrCMBCG4aw9RU5gJ+3YXsMrpDagErGkKeT4Vty48WdREOF9Nu9iZvGF4i9jDNU098MpuSoUt80lmzXJom31Xtft5LkPtTNOVRuRbqkR12itxsqqK16Yp+yTtWY892//Pt3/1D76Qzhe4xCSzaHkza8HAQAAAAAAAAAAAAAAAAC+cgOMxjgDACgAAA==',
                "contents": [
                    ("example/subdir1/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "1008e36e3235a2bd82ddbb7bf68e7767"
            },
            "subdir1.01": {
                "b64": b'H4sIAAAAAAAAA+3OTQrCMBiE4aw9RU5gk/QzuYZXaG1AJWJJU8jxq7hx48+iIML7bGYxs5hYu8uYYjPN/XDKtonVbUstak3mxnu5pw0785wPziorIq0xwYpXxrbigtJm1RcvzFPpstZqPPdvd5/6P7VP3SEer2mIWZdYy+bXhwAAAAAAAAAAAAAAAAAAX1kA/Ab9xAAoAAA=',
                "contents": [
                    ("example/subdir1/ex2.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "df145dac88a341d59709395361ddcb0c"
            },
            "subdir2.00": {
                "b64": b'H4sIAAAAAAAAA+3OSwrCMBSF4YxdRVZgkzQ223ALqb2gErGkKWT5Vpw48TEoiPB/kwP33MGRGi9jkmaa++GUXSPVbkstak1m0XX+njbszHM+OKus9741Jtiw3G3rnVfarLrihXkqMWutxnP/9u9T/6f2KR7keE2DZF2kls2vBwEAAAAAAAAAAAAAAAAAvnIDTYFecAAoAAA=',
                "contents": [
                    ("example/subdir2/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "aa1e47917b73e55ce84fbf5abbadac9c"
            },
            "subdir2.01": {
                "b64": b'H4sIAAAAAAAAA+3OSwrCMBSF4YxdRVZgkzRttuEWWntBJWJJU8jyW3HixMegIML/TQ7ccwdHSncdo1TT3A/n5Copbp9LVlsyq7b197ShMc/54Kyy3vvamGDDere1d43SZtMVL8xT7pLWarz0b/8+9X/qELujnG5xkKSzlLz79SAAAAAAAAAAAAAAAAAAwFcWnpOniAAoAAA=',
                "contents": [
                    ("example/subdir2/ex2.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "35f2b1326ed67ab2661d7a0aa1a1c277"
            },
            "miscellaneous.00": {
                "b64": b'H4sIAAAAAAAAA+3OMQrCQBSE4a09xZ5A34ub5BpeYdUHIiuG+IQ9vhEbsVCbIML/NVPMFGM1n4ZiK6u69OphDjLpunRP7Vt5zodGg6aU1iK9ShtEG5nqKLO8eXG9eB5jDMNx+3b3qf9Tm5J3djiXvY3Rrfri14cAAAAAAAAAAAAAAAAAAF+5AWYSJbwAKAAA',
                "contents": [
                    ("example/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "3c28749fd786eb199e6c2d20e224f7c9"
            },
            "miscellaneous.01": {
                "b64": b'H4sIAAAAAAAAA+3TOw6CQBSF4aldxaxA5iWzDbcAchM1GAkMySwfjY2JURuCkvxfc4p7i9McydWla6UYxro59b6QbLcpJzUnc1OW4Z427sxzPjirbAjBGxNtdMpYH1xU2sza4o1xSFWvterO9ce/b/eV2rfVQY7XtpFeJ8lp8+tCWJS87N/9xf69Yf9LYP8AAAAAAAAAAAAAAADrNgFkm3NNACgAAA==',
                "contents": [
                    ("example/subdir3/ex1.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7"),
                    ("example/subdir3/ex2.txt",
                     "d1ee10b76e42d7e06921e41fbb9b75f7")
                ],
                "md5": "6bb7bf22c1dd5b938c431c6696eb6af9"
            },
            "extra_file.txt": {
                "type": "file",
                "contents": "Extra stuff\n",
                "md5": "f299d91fe1d73319e4daa11dc3a12a33"
            }
        }
        # Build example archive dir
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archive"))
        md5s = []
        for name in MULTI_VOLUME_MULTIPLE_SUBARCHIVES_AND_FILE:
            data = MULTI_VOLUME_MULTIPLE_SUBARCHIVES_AND_FILE[name]
            # Check if it's actually a file
            if "type" in data:
                example_archive.add(name,
                                    type=data["type"],
                                    content=data["contents"])
                md5s.append((name,data['md5']))
                continue
            # Tar.gz file for subarchive
            example_archive.add("%s.tar.gz" % name,
                                type="binary",
                                content=base64.b64decode(data['b64']))
            # MD5 file for contents
            example_archive.add("%s.md5" % name,
                                type="file",
                                content='\n'.join(["%s  %s" %
                                                   (d[1],d[0])
                                                   for d in data['contents']]))
            # Store archive MD5
            md5s.append(("%s.tar.gz" % name,data['md5']))
        # MD5 for archive dir
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content='\n'.join(["%s  %s" % (m[1],m[0])
                                               for m in md5s]))
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "subarchives": [
    "subdir1.00.tar.gz",
    "subdir1.01.tar.gz",
    "subdir2.00.tar.gz",
    "subdir2.01.tar.gz",
    "miscellaneous.00.tar.gz",
    "miscellaneous.01.tar.gz"
  ],
  "files": [
    "extra_file.txt"
  ],
  "user": "anon",
  "creation_date": "23-06-16 09:58:39",
  "multi_volume": true,
  "volume_size": "250M",
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add(".ngsarchiver/manifest.txt",type="file")
        example_archive.create()
        p = example_archive.path
        # Expected contents
        expected = ('example/extra_file.txt',
                    'example/ex1.txt',
                    'example/subdir1',
                    'example/subdir1/ex1.txt',
                    'example/subdir1/ex2.txt',
                    'example/subdir2',
                    'example/subdir2/ex1.txt',
                    'example/subdir2/ex2.txt',
                    'example/subdir3',
                    'example/subdir3/ex1.txt',
                    'example/subdir3/ex2.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example")
        self.assertEqual(metadata['subarchives'],["subdir1.00.tar.gz",
                                                  "subdir1.01.tar.gz",
                                                  "subdir2.00.tar.gz",
                                                  "subdir2.01.tar.gz",
                                                  "miscellaneous.00.tar.gz",
                                                  "miscellaneous.01.tar.gz"])
        self.assertEqual(metadata['files'],["extra_file.txt"])
        self.assertEqual(metadata['multi_volume'],True)
        self.assertEqual(metadata['volume_size'],"250M")
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)

class TestArchiveDirMember(unittest.TestCase):

    def test_archive_dir_member(self):
        """
        ArchiveDirMember: check properties
        """
        m = ArchiveDirMember("path/to/member",
                             "subarchive.tar.gz",
                             "178fce553fbc42451c2fc43f9a965908")
        self.assertEqual(m.path,"path/to/member")
        self.assertEqual(m.subarchive,"subarchive.tar.gz")
        self.assertEqual(m.md5,"178fce553fbc42451c2fc43f9a965908")

class TestGetRundirInstance(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestGetRundirInstance')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_get_rundir_instance_generic_run(self):
        """
        get_rundir_instance: returns 'GenericRun' instance
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir2/ex3.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Check correct class is returned
        d = get_rundir_instance(p)
        self.assertTrue(isinstance(d,GenericRun))

    def test_get_rundir_instance_multi_subdir_run(self):
        """
        get_rundir_instance: returns 'MultiSubdirRun' instance
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir2/ex3.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Check correct class is returned
        d = get_rundir_instance(p)
        self.assertTrue(isinstance(d,MultiSubdirRun))

    def test_get_rundir_instance_multi_project_run(self):
        """
        get_rundir_instance: returns 'MultiProjectRun' instance
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("projects.info",type="file",
                        content="#Header\nProject1\tsome\tstuff\nProject2\tmore\tstuff\n")
        example_dir.add("Project1/README",type="file")
        example_dir.add("Project2/README",type="file")
        example_dir.add("undetermined/README",type="file")
        example_dir.add("processing_qc.html",type="file")
        example_dir.create()
        p = example_dir.path
        # Check correct class is returned
        d = get_rundir_instance(p)
        self.assertTrue(isinstance(d,MultiProjectRun))

    def test_get_rundir_instance_archive_directory(self):
        """
        get_rundir_instance: returns 'ArchiveDirectory' instance
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example.archive"))
        example_dir.add(".ngsarchiver/archive.md5",type="file")
        example_dir.add(".ngsarchiver/archive_metadata.json",type="file",
                        content="{}")
        example_dir.add(".ngsarchiver/manifest.txt",type="file")
        example_dir.add("Project1.tar.gz",type="file")
        example_dir.add("Project2.tar.gz",type="file")
        example_dir.add("undetermined.tar.gz",type="file")
        example_dir.add("processing.tar.gz",type="file")
        example_dir.add("Project1.md5",type="file")
        example_dir.add("Project2.md5",type="file")
        example_dir.add("undetermined.md5",type="file")
        example_dir.add("processing.md5",type="file")
        example_dir.create()
        p = example_dir.path
        p = example_dir.path
        # Check correct class is returned
        d = get_rundir_instance(p)
        self.assertTrue(isinstance(d,ArchiveDirectory))

class TestMakeArchiveDir(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMakeArchiveDir')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_make_archive_dir_single_archive(self):
        """
        make_archive_dir: single archive
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,out_dir=self.wd)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        for item in ("example.tar.gz",
                     "example.md5",
                     ".ngsarchiver",
                     ".ngsarchiver/archive.md5",
                     ".ngsarchiver/archive_metadata.json",
                     ".ngsarchiver/manifest.txt",):
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)

    def test_make_archive_dir_multiple_subarchives(self):
        """
        make_archive_dir: multiple subarchives
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("subdir1/ex1.txt",type="file",content="Some text\n")
        example_dir.add("subdir2/ex2.txt",type="file",content="Some text\n")
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,sub_dirs=('subdir1','subdir2'),
                             out_dir=self.wd)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        for item in ("subdir1.tar.gz",
                     "subdir1.md5",
                     "subdir2.tar.gz",
                     "subdir2.md5",
                     ".ngsarchiver",
                     ".ngsarchiver/archive.md5",
                     ".ngsarchiver/archive_metadata.json",
                     ".ngsarchiver/manifest.txt",):
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)

    def test_make_archive_dir_multiple_subarchives_including_misc(self):
        """
        make_archive_dir: multiple subarchives (including miscellaneous)
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("subdir1/ex1.txt",type="file",content="Some text\n")
        example_dir.add("subdir2/ex2.txt",type="file",content="Some text\n")
        example_dir.add("subdir3/ex3.txt",type="file",content="Some text\n")
        example_dir.add("ex4.txt",type="file",content="Some text\n")
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,sub_dirs=('subdir1','subdir2'),
                             misc_objects=('ex4.txt','subdir3'),
                             out_dir=self.wd)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        for item in ("subdir1.tar.gz",
                     "subdir1.md5",
                     "subdir2.tar.gz",
                     "subdir2.md5",
                     "miscellaneous.tar.gz",
                     "miscellaneous.md5",
                     ".ngsarchiver",
                     ".ngsarchiver/archive.md5",
                     ".ngsarchiver/archive_metadata.json",
                     ".ngsarchiver/manifest.txt",):
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)

    def test_make_archive_dir_multiple_subarchives_including_misc_and_extra_files(self):
        """
        make_archive_dir: multiple subarchives (including miscellaneous and extra files)
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("subdir1/ex1.txt",type="file",content="Some text\n")
        example_dir.add("subdir2/ex2.txt",type="file",content="Some text\n")
        example_dir.add("subdir3/ex3.txt",type="file",content="Some text\n")
        example_dir.add("ex4.txt",type="file",content="Some text\n")
        example_dir.add("ex5.txt",type="file",content="Some text\n")
        example_dir.add("ex6.txt",type="file",content="Some text\n")
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,sub_dirs=('subdir1','subdir2'),
                             misc_objects=('ex4.txt','subdir3'),
                             extra_files=('ex5.txt','ex6.txt'),
                             out_dir=self.wd)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        for item in ("subdir1.tar.gz",
                     "subdir1.md5",
                     "subdir2.tar.gz",
                     "subdir2.md5",
                     "miscellaneous.tar.gz",
                     "miscellaneous.md5",
                     "ex5.txt",
                     "ex6.txt",
                     ".ngsarchiver",
                     ".ngsarchiver/archive.md5",
                     ".ngsarchiver/archive_metadata.json",
                     ".ngsarchiver/manifest.txt",):
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)

    def test_make_archive_dir_multi_volume_single_archive(self):
        """
        make_archive_dir: single multi-volume archive
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add_batch(["ex%d.txt" % ix for ix in range(0,1)],
                              type="file",content=random_text(10000))
        example_dir.add_batch(["subdir/ex%d.txt" % ix for ix in range(0,1)],
                              type="file",content=random_text(10000))
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,out_dir=self.wd,volume_size='8K')
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        expected = ("example.00.tar.gz",
                    "example.01.tar.gz",
                    "example.00.md5",
                    "example.01.md5",
                    ".ngsarchiver",
                    ".ngsarchiver/archive.md5",
                    ".ngsarchiver/archive_metadata.json",
                    ".ngsarchiver/manifest.txt",)
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in a.walk():
            self.assertTrue(os.path.relpath(item,archive_dir) in expected,
                            "'%s' not expected" % item)

    def test_make_archive_dir_multi_volume_multiple_subarchives(self):
        """
        make_archive_dir: multiple multi-volume subarchives
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add_batch(["subdir1/ex%d.txt" % ix for ix in range(0,2)],
                              type="file",content=random_text(10000))
        example_dir.add_batch(["subdir2/ex%d.txt" % ix for ix in range(0,2)],
                              type="file",content=random_text(10000))
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,sub_dirs=('subdir1','subdir2'),
                             out_dir=self.wd,volume_size='8K')
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        expected = ("subdir1.00.tar.gz",
                    "subdir1.01.tar.gz",
                    "subdir2.00.tar.gz",
                    "subdir2.01.tar.gz",
                    "subdir1.00.md5",
                    "subdir1.01.md5",
                    "subdir2.00.md5",
                    "subdir2.01.md5",
                    ".ngsarchiver",
                    ".ngsarchiver/archive.md5",
                    ".ngsarchiver/archive_metadata.json",
                    ".ngsarchiver/manifest.txt",)
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in a.walk():
            self.assertTrue(os.path.relpath(item,archive_dir) in expected,
                            "'%s' not expected" % item)

    def test_make_archive_dir_multi_volume_multiple_subarchives_including_misc(self):
        """
        make_archive_dir: multiple multi-volume subarchives (including miscellaneous)
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add_batch(["subdir1/ex%d.txt" % ix for ix in range(0,2)],
                              type="file",content=random_text(10000))
        example_dir.add_batch(["subdir2/ex%d.txt" % ix for ix in range(0,2)],
                              type="file",content=random_text(10000))
        example_dir.add_batch(["subdir3/ex%d.txt" % ix for ix in range(0,2)],
                              type="file",content=random_text(10000))
        example_dir.add("ex4.txt",type="file",content="Some text\n")
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,sub_dirs=('subdir1','subdir2'),
                             misc_objects=('ex4.txt','subdir3'),
                             out_dir=self.wd,
                             volume_size='8K')
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        expected = ("subdir1.00.tar.gz",
                    "subdir1.01.tar.gz",
                    "subdir2.00.tar.gz",
                    "subdir2.01.tar.gz",
                    "subdir1.00.md5",
                    "subdir1.01.md5",
                    "subdir2.00.md5",
                    "subdir2.01.md5",
                    "miscellaneous.00.tar.gz",
                    "miscellaneous.01.tar.gz",
                    "miscellaneous.02.tar.gz",
                    "miscellaneous.00.md5",
                    "miscellaneous.01.md5",
                    "miscellaneous.02.md5",
                    ".ngsarchiver",
                    ".ngsarchiver/archive.md5",
                    ".ngsarchiver/archive_metadata.json",
                    ".ngsarchiver/manifest.txt",)
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in a.walk():
            self.assertTrue(os.path.relpath(item,archive_dir) in expected,
                            "'%s' not expected" % item)

    def test_make_archive_dir_multi_volume_multiple_subarchives_including_misc_and_extra_files(self):
        """
        make_archive_dir: multiple multi-volume subarchives (including miscellaneous and extra files)
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add_batch(["subdir1/ex%d.txt" % ix for ix in range(0,2)],
                              type="file",content=random_text(10000))
        example_dir.add_batch(["subdir2/ex%d.txt" % ix for ix in range(0,2)],
                              type="file",content=random_text(10000))
        example_dir.add_batch(["subdir3/ex%d.txt" % ix for ix in range(0,2)],
                              type="file",content=random_text(10000))
        example_dir.add("ex4.txt",type="file",content="Some text\n")
        example_dir.add("ex5.txt",type="file",content="Some text\n")
        example_dir.add("ex6.txt",type="file",content="Some text\n")
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,sub_dirs=('subdir1','subdir2'),
                             misc_objects=('ex4.txt','subdir3'),
                             extra_files=('ex5.txt','ex6.txt'),
                             out_dir=self.wd,
                             volume_size='8K')
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        expected = ("subdir1.00.tar.gz",
                    "subdir1.01.tar.gz",
                    "subdir2.00.tar.gz",
                    "subdir2.01.tar.gz",
                    "subdir1.00.md5",
                    "subdir1.01.md5",
                    "subdir2.00.md5",
                    "subdir2.01.md5",
                    "miscellaneous.00.tar.gz",
                    "miscellaneous.01.tar.gz",
                    "miscellaneous.02.tar.gz",
                    "miscellaneous.00.md5",
                    "miscellaneous.01.md5",
                    "miscellaneous.02.md5",
                    "ex5.txt",
                    "ex6.txt",
                    ".ngsarchiver",
                    ".ngsarchiver/archive.md5",
                    ".ngsarchiver/archive_metadata.json",
                    ".ngsarchiver/manifest.txt",)
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in a.walk():
            self.assertTrue(os.path.relpath(item,archive_dir) in expected,
                            "'%s' not expected" % item)

class TestMd5sum(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMd5sum')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_md5sum(self):
        """
        md5sum: generates expected MD5 sum for file
        """
        # Make example file
        test_file = os.path.join(self.wd,"example.txt")
        with open(test_file,'wt') as fp:
            fp.write("example text\n")
        # Check MD5 sum
        self.assertEqual(md5sum(test_file),
                         "9058c04d83e6715d15574b1b51fadba8")

class TestVerifyChecksums(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestVerifyChecksums')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_verify_checksums(self):
        """
        verify_checksums: checksums are correct
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        p = example_dir.path
        # Create checksum file
        checksums = {
            'ex1.txt': "8bcc714d327b74a95a166574d0103f5c",
            'subdir/ex2.txt': "cfac359b4837003003a79a3b237f1d32",
        }
        md5file = os.path.join(self.wd,"checksums.txt")
        with open(md5file,'wt') as fp:
            for f in checksums:
                fp.write(
                    "{checksum}  {path}/{file}\n".format(
                        path=p,
                        file=f,
                        checksum=checksums[f]))
        # Do verification
        self.assertTrue(verify_checksums(md5file))

    def test_verify_checksums_with_root_dir(self):
        """
        verify_checksums: specify a root directory
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        p = example_dir.path
        # Create checksum file
        checksums = {
            'ex1.txt': "8bcc714d327b74a95a166574d0103f5c",
            'subdir/ex2.txt': "cfac359b4837003003a79a3b237f1d32",
        }
        md5file = os.path.join(self.wd,"checksums.txt")
        with open(md5file,'wt') as fp:
            for f in checksums:
                fp.write(
                    "{checksum}  {file}\n".format(
                        file=f,
                        checksum=checksums[f]))
        # Do verification
        self.assertTrue(verify_checksums(md5file,root_dir=p))

    def test_verify_checksums_different_md5(self):
        """
        verify_checksums: fails when MD5 sums differ
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        p = example_dir.path
        # Create checksum file with 'bad' MD5 sum
        checksums = {
            'ex1.txt': "8bcc714d327b74a95a166574d0103f5c",
            'subdir/ex2.txt': "6b97f2f07bb2b9504978d86264bf1f45",
        }
        md5file = os.path.join(self.wd,"checksums.txt")
        with open(md5file,'wt') as fp:
            for f in checksums:
                fp.write(
                    "{checksum}  {path}/{file}\n".format(
                        path=p,
                        file=f,
                        checksum=checksums[f]))
        # Do verification
        self.assertFalse(verify_checksums(md5file))

    def test_verify_checksums_missing_file(self):
        """
        verify_checksums: fails when file is missing
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        p = example_dir.path
        # Create checksum file with non-existent file
        checksums = {
            'ex1.txt': "8bcc714d327b74a95a166574d0103f5c",
            'subdir/ex2.txt': "cfac359b4837003003a79a3b237f1d32",
            'missing.txt': "6b97f2f07bb2b9504978d86264bf1f45",
        }
        md5file = os.path.join(self.wd,"checksums.txt")
        with open(md5file,'wt') as fp:
            for f in checksums:
                fp.write(
                    "{checksum}  {path}/{file}\n".format(
                        path=p,
                        file=f,
                        checksum=checksums[f]))
        # Do verification
        self.assertFalse(verify_checksums(md5file))

    def test_verify_checksums_bad_checksum_line(self):
        """
        verify_checksums: raises exception for 'bad' checksum line
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        p = example_dir.path
        # Create checksum file bad line
        checksums = {
            'ex1.txt': "8bcc714d327b74a95a166574d0103f5c",
            'subdir/ex2.txt': "cfac359b4837003003a79a3b237f1d32",
        }
        md5file = os.path.join(self.wd,"checksums.txt")
        with open(md5file,'wt') as fp:
            for f in checksums:
                fp.write(
                    "{checksum}  {path}/{file}\n".format(
                        path=p,
                        file=f,
                        checksum=checksums[f]))
                # Add a 'bad' line
                fp.write("blah blah\n")
        # Do verification
        self.assertRaises(NgsArchiverException,
                          verify_checksums,
                          md5file)

class TestMakeArchiveTgz(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMakeArchiveTgz')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_make_archive_tgz(self):
        """
        make_archive_tgz: archive with defaults
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text")
        example_dir.add("subdir/ex2.txt",type="file",content="More text")
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_path = "%s.tar.gz" % test_archive
        self.assertEqual(make_archive_tgz(test_archive,p),test_archive_path)
        # Check archive exists
        self.assertTrue(os.path.exists(test_archive_path))
        # Check archive contains only expected members
        expected = set(("ex1.txt",
                        "subdir",
                        "subdir/ex2.txt",))
        members = set()
        with tarfile.open(test_archive_path,"r:gz") as tgz:
            for f in tgz.getnames():
                self.assertTrue(f in expected)
                members.add(f)
        # Check no expected members are missing from the archive
        for f in expected:
            self.assertTrue(f in members)

    def test_make_archive_tgz_with_base_dir(self):
        """
        make_archive_tgz: archive with base directory
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text")
        example_dir.add("subdir/ex2.txt",type="file",content="More text")
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_path = "%s.tar.gz" % test_archive
        self.assertEqual(make_archive_tgz(test_archive,p,base_dir="example"),
                         test_archive_path)
        # Check archive exists
        self.assertTrue(os.path.exists(test_archive_path))
        # Check archive contains only expected members
        expected = set(("example/ex1.txt",
                        "example/subdir",
                        "example/subdir/ex2.txt",))
        members = set()
        with tarfile.open(test_archive_path,"r:gz") as tgz:
            for f in tgz.getnames():
                self.assertTrue(f in expected)
                members.add(f)
        # Check no expected members are missing from the archive
        for f in expected:
            self.assertTrue(f in members)

    def test_make_archive_tgz_with_file_list(self):
        """
        make_archive_tgz: specify file list
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text")
        example_dir.add("subdir/ex2.txt",type="file",content="More text")
        example_dir.add("subdir/exclude.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_path = "%s.tar.gz" % test_archive
        included_files = [os.path.join(p,f)
                          for f in ("ex1.txt",
                                    "subdir",
                                    "subdir/ex2.txt")]
        self.assertEqual(make_archive_tgz(test_archive,p,
                                          file_list=included_files),
                         test_archive_path)
        # Check archive exists
        self.assertTrue(os.path.exists(test_archive_path))
        # Check archive contains only expected members
        expected = set(("ex1.txt",
                        "subdir",
                        "subdir/ex2.txt",))
        members = set()
        with tarfile.open(test_archive_path,"r:gz") as tgz:
            for f in tgz.getnames():
                print(f)
                self.assertTrue(f in expected)
                members.add(f)
        # Check no expected members are missing from the archive
        for f in expected:
            print(f)
            self.assertTrue(f in members)

    def test_make_archive_tgz_non_default_compression_level(self):
        """
        make_archive_tgz: archive with non-default compression level
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text")
        example_dir.add("subdir/ex2.txt",type="file",content="More text")
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_path = "%s.tar.gz" % test_archive
        self.assertEqual(make_archive_tgz(test_archive,p,
                                          compresslevel=1),
                         test_archive_path)
        # Check archive exists
        self.assertTrue(os.path.exists(test_archive_path))
        # Check archive contains only expected members
        expected = set(("ex1.txt",
                        "subdir",
                        "subdir/ex2.txt",))
        members = set()
        with tarfile.open(test_archive_path,"r:gz") as tgz:
            for f in tgz.getnames():
                self.assertTrue(f in expected)
                members.add(f)
        # Check no expected members are missing from the archive
        for f in expected:
            self.assertTrue(f in members)

class TestMakeArchiveMultiTgz(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMakeArchiveMultiTgz')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_make_archive_multitgz(self):
        """
        make_archive_multitgz: archive setting volume size
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add_batch(["ex%d.txt" % ix for ix in range(0,25)],
                              type="file",content=random_text(10000))
        example_dir.add_batch(["subdir/ex%d.txt" % ix for ix in range(0,25)],
                              type="file",content=random_text(10000))
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_paths = ["%s.%02d.tar.gz" % (test_archive,ix)
                              for ix in range(0,2)]
        self.assertEqual(make_archive_multitgz(test_archive,p,size='16K'),
                         test_archive_paths)
        # Check archives contains only expected members
        expected = set(example_dir.list())
        members = set()
        for test_archive_path in test_archive_paths:
            # Check archive exists
            self.assertTrue(os.path.exists(test_archive_path))
            # Check contents
            with tarfile.open(test_archive_path,"r:gz") as tgz:
                for f in tgz.getnames():
                    self.assertTrue(f in expected)
                    self.assertFalse(f in members)
                    members.add(f)
        # Check no expected members are missing from the archive
        for f in expected:
            self.assertTrue(f in members)

    def test_make_archive_multitgz_with_base_dir(self):
        """
        make_archive_multitgz: archive with base directory
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add_batch(("ex%d.txt" % ix for ix in range(0,25)),
                              type="file",content=random_text(10000))
        example_dir.add_batch(("subdir/ex%d.txt" % ix for ix in range(0,25)),
                              type="file",content=random_text(10000))
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_paths = ["%s.%02d.tar.gz" % (test_archive,ix)
                              for ix in range(0,2)]
        self.assertEqual(make_archive_multitgz(test_archive,p,
                                               base_dir="example",
                                               size='16K'),
                         test_archive_paths)
        # Check archives contains only expected members
        expected = set(example_dir.list(prefix="example"))
        members = set()
        for test_archive_path in test_archive_paths:
            # Check archive exists
            self.assertTrue(os.path.exists(test_archive_path))
            # Check contents
            with tarfile.open(test_archive_path,"r:gz") as tgz:
                for f in tgz.getnames():
                    self.assertTrue(f in expected)
                    self.assertFalse(f in members)
                    members.add(f)
        # Check no expected members are missing from the archive
        for f in expected:
            self.assertTrue(f in members)

    def test_make_archive_multitgz_with_file_list(self):
        """
        make_archive_multitgz: archive with file list
        """
        # Build example dir
        text = random_text(5000)
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add_batch(("ex%d.txt" % ix for ix in range(0,50)),
                              type="file",content=text)
        example_dir.add_batch(("subdir/ex%d.txt" % ix for ix in range(0,50)),
                              type="file",content=text)
        example_dir.create()
        p = example_dir.path
        # Overlay example dir with a subset of files
        # Only needed to generate a list of files
        overlay_dir = UnittestDir(os.path.join(self.wd,"example"))
        overlay_dir.add_batch(("ex%d.txt" % ix for ix in range(0,50,2)),
                              type="file")
        overlay_dir.add_batch(("subdir/ex%d.txt" % ix for ix in range(0,50,2)),
                              type="file")
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_paths = ["%s.%02d.tar.gz" % (test_archive,ix)
                              for ix in range(0,1)]
        included_files = overlay_dir.list(prefix=p)
        self.assertEqual(make_archive_multitgz(test_archive,p,
                                               size='16K',
                                               file_list=included_files),
                         test_archive_paths)
        # Check archives contains only expected members
        expected = set(overlay_dir.list())
        members = set()
        for test_archive_path in test_archive_paths:
            # Check archive exists
            self.assertTrue(os.path.exists(test_archive_path))
            # Check contents
            with tarfile.open(test_archive_path,"r:gz") as tgz:
                for f in tgz.getnames():
                    self.assertTrue(f in expected)
                    self.assertFalse(f in members)
                    members.add(f)
        # Check no expected members are missing from the archive
        for f in expected:
            self.assertTrue(f in members)

    def test_make_archive_multitgz_non_default_compression_level(self):
        """
        make_archive_multitgz: archive setting volume size
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add_batch(["ex%d.txt" % ix for ix in range(0,25)],
                              type="file",content=random_text(10000))
        example_dir.add_batch(["subdir/ex%d.txt" % ix for ix in range(0,25)],
                              type="file",content=random_text(10000))
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_paths = ["%s.%02d.tar.gz" % (test_archive,ix)
                              for ix in range(0,2)]
        self.assertEqual(make_archive_multitgz(test_archive,p,
                                               size='16K',
                                               compresslevel=1),
                         test_archive_paths)
        # Check archives contains only expected members
        expected = set(example_dir.list())
        members = set()
        for test_archive_path in test_archive_paths:
            # Check archive exists
            self.assertTrue(os.path.exists(test_archive_path))
            # Check contents
            with tarfile.open(test_archive_path,"r:gz") as tgz:
                for f in tgz.getnames():
                    self.assertTrue(f in expected)
                    self.assertFalse(f in members)
                    members.add(f)
        # Check no expected members are missing from the archive
        for f in expected:
            self.assertTrue(f in members)

class TestUnpackArchiveMultiTgz(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestUnpackArchiveMultiTgz')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_unpack_archive_multitgz_single_tar_gz(self):
        """
        unpack_archive_multitgz: single .tar.gz file
        """
        # Make example tar.gz file
        example_targz = os.path.join(self.wd,"example.tar.gz")
        with open(example_targz,'wb') as fp:
            # Encodes a tar.gz file with the contents in
            # 'expected' (below)
            fp.write(base64.b64decode(b'H4sIAAAAAAAAA+2ZYWqDQBCF/Z1TeIJkdxzda/QKpllog6HBbMDjd7QVopKWQJxt2ff9MehCFl6+8Wl8V5/Ojd9lK2IE58r+aF1pbo8jmWXmQpZZI+usqchmebnmpkaul1C3eZ6dj/sf1/12/Z/iv/O/XPeH95ZW+R08lL+T85bkOvLXYJ6/72gbuvDU7+gDriq+n7/IPs2/YJL8zVN3cYfE839p6lf/9tEcfJsH34VN7A0BVZb+27/hP8N/DeB/2kz9t/H7H1df/c+h/2kwzz96/xvyl/nvMP81wPxPm6X/kfsfM/qfIvA/bab+F/H7n6O+/5GcQv9TYJ5/9P435F/IZ8x/DTD/02bpf+z3f4TnP0Xgf9qM/q/h/chD/g///5Mpcf9XAf4DAECafAIvyELwACgAAA=='))
        expected = ('example',
                    'example/ex1.txt',
                    'example/subdir1',
                    'example/subdir1/ex1.txt',
                    'example/subdir1/ex2.txt',
                    'example/subdir2',
                    'example/subdir2/ex1.txt',
                    'example/subdir2/ex2.txt',
                    'example/subdir3',
                    'example/subdir3/ex1.txt',
                    'example/subdir3/ex2.txt',)
        # Unpack the targz file
        unpack_archive_multitgz((example_targz,),extract_dir=self.wd)
        # Check unpacked directory
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)

    def test_unpack_archive_multitgz_multiple_tar_gz(self):
        """
        unpack_archive_multitgz: multiple .tar.gz files
        """
        # Make example tar.gz files
        example_targz_data = [
            { 'path': os.path.join(self.wd,"subdir1.tar.gz"),
              'b64content': b'H4sIAAAAAAAAA+3T3QqCMBjG8R13FV5BbnO62+gWNAcVRqILdvkpEYRhnfiB9P+dvAd7YS88PC7k17pycXsvynOjYjED2bE27aeyqXyfL0IZY5JuTZlMSKWVtSJK5zhm6N76vIkiUV+Kr3u/3jfKDfJ3Qe998JP+0QecZWY8f60G+SdGd/nLSa8Y8ef5H6r86E63qnRN5F3wu7UPwqI++69W7r959t/Q/yXQfwAAAAAAAAAAAAAAtu8BVJJOSAAoAAA=',
              'expected': ('example/subdir1',
                           'example/subdir1/ex1.txt',
                           'example/subdir1/ex2.txt',),
            },
            { 'path': os.path.join(self.wd,"subdir2.tar.gz"),
              'b64content': b'H4sIAAAAAAAAA+3T0QqCMBTG8V33FHuCdHO61+gVNAcVRqITfPzmRRCGdaOW9P/dHNg5sAMfx/X5ta5c1HZFeW50JBYQB9amQ1U2jZ/rg1DGmCSMKRvelQ59IdMllhnrWp83Uor6Uryd+9TfKDfK3/V673s/6x9DwFlmpvPXapR/YnTIP551iwl/nv+hyo/udKtK10jver/79kJY1ev9q9+4f8P9r4H7BwAAAAAAAAAAAABg++79kqV0ACgAAA==',
              'expected': ('example/subdir2',
                           'example/subdir2/ex1.txt',
                           'example/subdir2/ex2.txt',),
            },
            { 'path': os.path.join(self.wd,"miscellaneous.tar.gz"),
              'b64content': b'H4sIAAAAAAAAA+3W0QrCIBQGYK97Cp+gHZ3O1+gVtiZULBqbAx8/V0GxqCjmovZ/N4oOdkD+o9bn+7qyifVi6bxjMVCQZaofhdF0O55JwYRSKiUygjQjISlsc4pSzUDXurzhnNW74ul3r/Z/1KrK13ZzqErbcGe9W3y7IJiUveS/7Ypy26RJjH/0ETdGP84/0TX/Rvb5l2GJ6xjFDM08/8Pzt16Ofg+81f9P55+GOfr/FND/5+0+/+O/Az/JvzTI/xSQfwAAAAAAAAAAAAAAAID/cQRHXCooACgAAA==',
              'expected': ('example/ex1.txt',
                           'example/subdir3',
                           'example/subdir3/ex1.txt',
                           'example/subdir3/ex2.txt',),
            }
        ]
        for targz in example_targz_data:
            example_targz = targz['path']
            with open(example_targz,'wb') as fp:
                fp.write(base64.b64decode(targz['b64content']))
        # Unpack the targz files
        example_targzs = [t['path'] for t in example_targz_data]
        unpack_archive_multitgz(example_targzs,extract_dir=self.wd)
        # Check unpacked directories
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        all_expected = []
        for targz in example_targz_data:
            expected = targz['expected']
            for item in expected:
                self.assertTrue(
                    os.path.exists(os.path.join(self.wd,item)),
                    "missing '%s'" % item)
                all_expected.append(item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in all_expected,
                            "'%s' not expected" % item)

class TestGetSize(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestGetSize')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_getsize_file(self):
        """
        getsize: get size for regular file
        """
        # Make example file
        test_file = os.path.join(self.wd,"example.txt")
        with open(test_file,'wt') as fp:
            fp.write("example text\n")
        # Check size
        self.assertEqual(getsize(test_file),4096)

    def test_getsize_symlink(self):
        """
        getsize: get size for symlink
        """
        # Make example file and symlink
        test_file = os.path.join(self.wd,"example.txt")
        with open(test_file,'wt') as fp:
            fp.write("example text\n")
        test_symlink = os.path.join(self.wd,"example_symlink.txt")
        os.symlink("example.txt",test_symlink)
        # Check size
        self.assertEqual(getsize(test_symlink),0)

    def test_getsize_dir(self):
        """
        getsize: get size for directory
        """
        self.assertEqual(getsize(self.wd),4096)

class TestConvertSizeToBytes(unittest.TestCase):

    def test_convert_size_to_bytes(self):
        """
        convert_size_to_bytes: handle different inputs
        """
        self.assertEqual(convert_size_to_bytes('4.0K'),4096)
        self.assertEqual(convert_size_to_bytes('4.0M'),4194304)
        self.assertEqual(convert_size_to_bytes('4.0G'),4294967296)
        self.assertEqual(convert_size_to_bytes('4.0T'),4398046511104)
        self.assertEqual(convert_size_to_bytes('4T'),4398046511104)

class TestFormatSize(unittest.TestCase):

    def test_format_size(self):
        """
        format_size: convert to specific units
        """
        self.assertEqual(format_size(4096,units='K'),4)
        self.assertEqual(format_size(4194304,units='M'),4)
        self.assertEqual(format_size(4294967296,units='G'),4)
        self.assertEqual(format_size(4398046511104,units='T'),4)

    def test_format_size_human_readable(self):
        """
        format_size: convert to human readable format
        """
        self.assertEqual(format_size(4096,human_readable=True),'4.0K')
        self.assertEqual(format_size(4194304,human_readable=True),'4.0M')
        self.assertEqual(format_size(4294967296,human_readable=True),'4.0G')
        self.assertEqual(format_size(4398046511104,human_readable=True),'4.0T')
