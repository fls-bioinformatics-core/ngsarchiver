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
        # type is one of 'file', 'dir', 'symlink', 'link'
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
        example_dir.add("symlink1",type="symlink",target="./ext1.txt")
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
        self.assertEqual(list(d.hard_linked_files),
                         [hard_link_src,hard_link_dst])
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
        user = os.getlogin()
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
        user = os.getlogin()
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
        GenericRun: placeholder
        """
        self.skipTest("Not implemented")

class TestMultiSubdirRun(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMultiSubdirRun')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_multisubdirrun(self):
        """
        MultiSubdirRun: placeholder
        """
        self.skipTest("Not implemented")

class TestMultiProjectRun(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMultiProjectRun')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_multiprojectrun(self):
        """
        MultiProjectRun: placeholder
        """
        self.skipTest("Not implemented")

class TestArchiveDirectory(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestArchiveDirectory')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_archivedirectory(self):
        """
        ArchiveDirectory: placeholder
        """
        self.skipTest("Not implemented")

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

    def test_make_archive_dir(self):
        """
        make_archive_dir: placeholder
        """
        self.skipTest("Not implemented")

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

    def test_unpack_archive_multitgz(self):
        """
        unpack_archive_multitgz: placeholder
        """
        self.skipTest("Not implemented")

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
