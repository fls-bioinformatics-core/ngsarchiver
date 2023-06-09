# Unit tests for the 'archive' module

import os
import pwd
import grp
import unittest
import tempfile
import shutil
from ngsarchiver.archive import Directory
from ngsarchiver.archive import GenericRun
from ngsarchiver.archive import MultiSubdirRun
from ngsarchiver.archive import MultiProjectRun
from ngsarchiver.archive import ArchiveDirectory
from ngsarchiver.archive import ArchiveDirMember
from ngsarchiver.archive import get_rundir_instance

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
            print("...creatting '%s' (%s)" % (p,type_))
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
