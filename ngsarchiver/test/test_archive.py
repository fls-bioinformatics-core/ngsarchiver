# Unit tests for the 'archive' module

import os
import pwd
import grp
import re
import unittest
import tempfile
import tarfile
import random
import string
import shutil
import base64
import getpass
from ngsarchiver.archive import Path
from ngsarchiver.archive import Directory
from ngsarchiver.archive import GenericRun
from ngsarchiver.archive import MultiSubdirRun
from ngsarchiver.archive import MultiProjectRun
from ngsarchiver.archive import ArchiveDirectory
from ngsarchiver.archive import ArchiveDirMember
from ngsarchiver.archive import CopyArchiveDirectory
from ngsarchiver.archive import ReadmeFile
from ngsarchiver.archive import get_rundir_instance
from ngsarchiver.archive import md5sum
from ngsarchiver.archive import verify_checksums
from ngsarchiver.archive import make_archive_dir
from ngsarchiver.archive import make_archive_tgz
from ngsarchiver.archive import make_archive_multitgz
from ngsarchiver.archive import unpack_archive_multitgz
from ngsarchiver.archive import make_copy
from ngsarchiver.archive import make_manifest_file
from ngsarchiver.archive import make_visual_tree_file
from ngsarchiver.archive import check_make_symlink
from ngsarchiver.archive import check_case_sensitive_filenames
from ngsarchiver.archive import getsize
from ngsarchiver.archive import convert_size_to_bytes
from ngsarchiver.archive import format_size
from ngsarchiver.archive import format_bool
from ngsarchiver.archive import group_case_sensitive_names
from ngsarchiver.archive import tree
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


class TestPath(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestPath')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_path_is_regular_file(self):
        """
        Path: check regular file
        """
        f = os.path.join(self.wd, "file1.txt")
        with open(f, "wt") as fp:
            fp.write("Placeholder")
        self.assertTrue(Path(f).is_file())
        self.assertFalse(Path(f).is_hardlink())
        self.assertFalse(Path(f).is_dirlink())
        self.assertFalse(Path(f).is_broken_symlink())
        self.assertFalse(Path(f).is_unresolvable_symlink())

    def test_path_is_directory(self):
        """
        Path: check regular directory
        """
        d = os.path.join(self.wd, "dir1")
        os.makedirs(d)
        self.assertTrue(Path(d).is_dir())
        self.assertFalse(Path(d).is_hardlink())
        self.assertFalse(Path(d).is_dirlink())
        self.assertFalse(Path(d).is_broken_symlink())
        self.assertFalse(Path(d).is_unresolvable_symlink())

    def test_path_is_symlink(self):
        """
        Path: check regular symlink
        """
        f = os.path.join(self.wd, "file1.txt")
        with open(f, "wt") as fp:
            fp.write("Placeholder")
        s = os.path.join(self.wd, "symlink1")
        os.symlink(f, s)
        self.assertTrue(Path(s).is_symlink())
        self.assertFalse(Path(s).is_hardlink())
        self.assertFalse(Path(s).is_dirlink())
        self.assertFalse(Path(s).is_broken_symlink())
        self.assertFalse(Path(s).is_unresolvable_symlink())

    def test_path_is_dirlink(self):
        """
        Path: check dirlink
        """
        d = os.path.join(self.wd, "dir1")
        os.makedirs(d)
        s = os.path.join(self.wd, "dirlink1")
        os.symlink(d, s)
        self.assertTrue(Path(s).is_symlink())
        self.assertTrue(Path(s).is_dirlink())
        self.assertFalse(Path(s).is_hardlink())
        self.assertFalse(Path(s).is_broken_symlink())
        self.assertFalse(Path(s).is_unresolvable_symlink())

    def test_path_is_broken_symlink(self):
        """
        Path: check broken symlink
        """
        s = os.path.join(self.wd, "broken_symlink")
        os.symlink("doesnt_exist", s)
        self.assertTrue(Path(s).is_symlink())
        self.assertTrue(Path(s).is_broken_symlink())
        self.assertFalse(Path(s).is_hardlink())
        self.assertFalse(Path(s).is_dirlink())
        self.assertFalse(Path(s).is_unresolvable_symlink())

    def test_path_is_hard_link(self):
        """
        Path: check hard linked file
        """
        f = os.path.join(self.wd, "file1.txt")
        with open(f, "wt") as fp:
            fp.write("Placeholder")
        h = os.path.join(self.wd, "hard_link1.txt")
        os.link(f, h)
        self.assertTrue(Path(h).is_file())
        self.assertTrue(Path(h).is_hardlink())
        self.assertFalse(Path(h).is_dirlink())
        self.assertFalse(Path(h).is_broken_symlink())
        self.assertFalse(Path(h).is_unresolvable_symlink())

    def test_path_is_symlink_loop_single_symlink(self):
        """
        Path: check symlink loop (symlink points to itself)
        """
        s = os.path.join(self.wd, "symlink_to_self")
        os.symlink(s, s)
        self.assertTrue(Path(s).is_symlink())
        self.assertTrue(Path(s).is_unresolvable_symlink())
        self.assertFalse(Path(s).is_hardlink())
        self.assertFalse(Path(s).is_dirlink())
        self.assertFalse(Path(s).is_broken_symlink())
        # Check unresolvable symlinks don't upset 'is_dir'
        self.assertFalse(Path(s).is_dir())

    def test_path_is_symlink_loop_pair_of_symlink(self):
        """
        Path: check symlink loop (symlinks point to each other)
        """
        s1 = os.path.join(self.wd, "symlink1")
        s2 = os.path.join(self.wd, "symlink2")
        os.symlink(s1, s2)
        os.symlink(s2, s1)
        self.assertTrue(Path(s1).is_symlink())
        self.assertTrue(Path(s1).is_unresolvable_symlink())
        self.assertFalse(Path(s1).is_hardlink())
        self.assertFalse(Path(s1).is_dirlink())
        self.assertFalse(Path(s1).is_broken_symlink())
        # Check unresolvable symlinks don't upset 'is_dir'
        self.assertFalse(Path(s1).is_dir())

    def test_path_is_symlink_to_broken_symlink(self):
        """
        Path: check symlink to broken symlink
        """
        b = os.path.join(self.wd, "broken_symlink")
        os.symlink("doesnt_exist", b)
        s = os.path.join(self.wd, "symlink_to_broken")
        os.symlink(b, s)
        self.assertTrue(Path(s).is_symlink())
        self.assertTrue(Path(s).is_broken_symlink())
        self.assertFalse(Path(s).is_hardlink())
        self.assertFalse(Path(s).is_dirlink())
        self.assertFalse(Path(s).is_unresolvable_symlink())

    def test_path_is_symlink_to_inaccessible_file(self):
        """
        Path: check symlink to inaccessible file
        """
        # "Inaccessible file" is a file under a directory
        # which is not readable by the current user
        d = os.path.join(self.wd, "dir")
        os.makedirs(d)
        f = os.path.join(d, "file")
        with open(f, "wt") as fp:
            fp.write("some content")
        s = os.path.join(self.wd, "symlink")
        os.symlink(f, s)
        self.assertTrue(Path(s).is_symlink())
        self.assertFalse(Path(s).is_broken_symlink())
        self.assertFalse(Path(s).is_hardlink())
        self.assertFalse(Path(s).is_dirlink())
        self.assertFalse(Path(s).is_unresolvable_symlink())
        # Make subdirectory unreadable
        try:
            os.chmod(d, 0o000)
            self.assertTrue(Path(s).is_symlink())
            self.assertTrue(Path(s).is_broken_symlink())
            self.assertFalse(Path(s).is_hardlink())
            self.assertFalse(Path(s).is_dirlink())
            self.assertFalse(Path(s).is_unresolvable_symlink())
        finally:
            os.chmod(d, 0o777)

    def test_path_owner(self):
        """
        Path: check 'owner' works for different cases
        """
        # Current user
        username = getpass.getuser()
        # Regular file
        f = os.path.join(self.wd, "file1.txt")
        with open(f, "wt") as fp:
            fp.write("Placeholder")
        self.assertEqual(Path(f).owner(), username)
        # Regular directory
        d = os.path.join(self.wd, "dir1")
        os.makedirs(d)
        self.assertEqual(Path(d).owner(), username)
        # Symlink
        s = os.path.join(self.wd, "symlink1")
        os.symlink(f, s)
        self.assertEqual(Path(s).owner(), username)
        # Dirlink
        s = os.path.join(self.wd, "dirlink1")
        os.symlink(d, s)
        self.assertEqual(Path(s).owner(), username)
        # Broken symlink
        s = os.path.join(self.wd, "broken_symlink")
        os.symlink("doesnt_exist", s)
        self.assertEqual(Path(s).owner(), username)
        # Hard linked file
        h = os.path.join(self.wd, "hard_link1.txt")
        os.link(f, h)
        self.assertEqual(Path(h).owner(), username)
        # Symlink to self
        s = os.path.join(self.wd, "symlink_to_self")
        os.symlink(s, s)
        self.assertEqual(Path(h).owner(), username)

    def test_path_group(self):
        """
        Path: check 'group' works for different cases
        """
        # Current group
        groupname = grp.getgrgid(
            pwd.getpwnam(getpass.getuser()).pw_gid).gr_name
        # Regular file
        f = os.path.join(self.wd, "file1.txt")
        with open(f, "wt") as fp:
            fp.write("Placeholder")
        self.assertEqual(Path(f).group(), groupname)
        # Regular directory
        d = os.path.join(self.wd, "dir1")
        os.makedirs(d)
        self.assertEqual(Path(d).group(), groupname)
        # Symlink
        s = os.path.join(self.wd, "symlink1")
        os.symlink(f, s)
        self.assertEqual(Path(s).group(), groupname)
        # Dirlink
        s = os.path.join(self.wd, "dirlink1")
        os.symlink(d, s)
        self.assertEqual(Path(s).group(), groupname)
        # Broken symlink
        s = os.path.join(self.wd, "broken_symlink")
        os.symlink("doesnt_exist", s)
        self.assertEqual(Path(s).group(), groupname)
        # Hard linked file
        h = os.path.join(self.wd, "hard_link1.txt")
        os.link(f, h)
        self.assertEqual(Path(h).group(), groupname)
        # Symlink to self
        s = os.path.join(self.wd, "symlink_to_self")
        os.symlink(s, s)
        self.assertEqual(Path(h).group(), groupname)


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
        self.assertEqual(d.largest_file,("ex1.txt",4096))
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

    def test_directory_symlinks(self):
        """
        Directory: check handling of symlinks
        """
        # Build example dir without symlinks
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.create()
        p = example_dir.path
        # No symlinks should be detected
        d = Directory(p)
        self.assertEqual(list(d.symlinks),[])
        self.assertFalse(d.has_symlinks)
        # Add symlink
        symlink = os.path.join(p,"symlink2")
        os.symlink("ex1.txt", symlink)
        # Symlink should be detected
        self.assertEqual(list(d.symlinks), [symlink,])
        self.assertTrue(d.has_symlinks)

    def test_directory_external_symlinks(self):
        """
        Directory: check handling of external symlinks
        """
        # Build example dir without external symlinks
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./ex1.txt")
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
        # Build example dir without broken symlinks
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./ex1.txt")
        example_dir.create()
        p = example_dir.path
        # No broken symlinks or unreadable files should be detected
        # and unknown UID detection should function correctly
        d = Directory(p)
        self.assertEqual(list(d.broken_symlinks),[])
        self.assertFalse(d.has_broken_symlinks)
        self.assertEqual(list(d.unreadable_files),[])
        self.assertTrue(d.is_readable)
        self.assertEqual(list(d.unknown_uids),[])
        self.assertFalse(d.has_unknown_uids)
        # Add broken symlink
        broken_symlink = os.path.join(p,"broken")
        os.symlink("./missing.txt",broken_symlink)
        # Broken symlink should be detected but no unreadable files,
        # and unknown UID detection should function correctly
        self.assertEqual(list(d.broken_symlinks),[broken_symlink,])
        self.assertTrue(d.has_broken_symlinks)
        self.assertEqual(list(d.unreadable_files),[])
        self.assertTrue(d.is_readable)
        self.assertEqual(list(d.unknown_uids),[])
        self.assertFalse(d.has_unknown_uids)

    def test_directory_unresolvable_symlinks(self):
        """
        Directory: check handling of unresolvable symlinks
        """
        # Build example dir without unresolvable symlinks
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./ex1.txt")
        example_dir.create()
        p = example_dir.path
        # No unresolvable symlinks or unreadable files should be
        # detected and unknown UID detection should function correctly
        d = Directory(p)
        self.assertEqual(list(d.unresolvable_symlinks),[])
        self.assertFalse(d.has_unresolvable_symlinks)
        self.assertEqual(list(d.unreadable_files),[])
        self.assertTrue(d.is_readable)
        self.assertEqual(list(d.unknown_uids),[])
        self.assertFalse(d.has_unknown_uids)
        # Also check external symlinks
        self.assertEqual(list(d.external_symlinks), [])
        self.assertFalse(d.has_external_symlinks)
        # Add unresolvable symlink loop
        unresolvable_symlink = os.path.join(p,"unresolvable")
        os.symlink("./unresolvable",unresolvable_symlink)
        # Unresolvable symlink should be detected but no unreadable
        # files and unknown UID detection should function correctly
        self.assertEqual(list(d.unresolvable_symlinks),
                         [unresolvable_symlink,])
        self.assertTrue(d.has_unresolvable_symlinks)
        self.assertEqual(list(d.unreadable_files),[])
        self.assertTrue(d.is_readable)
        self.assertEqual(list(d.unknown_uids),[])
        self.assertFalse(d.has_unknown_uids)
        # Also check external symlinks
        self.assertEqual(list(d.external_symlinks), [])
        self.assertFalse(d.has_external_symlinks)

    def test_directory_dirlinks(self):
        """
        Directory: check reporting of dirlinks
        """
        # Build example dir without dirlinks
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("subdir1",type="dir")
        example_dir.create()
        p = example_dir.path
        # No dirlinks should be detected
        d = Directory(p)
        self.assertEqual(list(d.dirlinks),[])
        self.assertFalse(d.has_dirlinks)
        # Add dirlink
        dirlink = os.path.join(p,"dirlink1")
        os.symlink("./subdir1",dirlink)
        # Dirlink should be detected
        self.assertEqual(list(d.dirlinks),[dirlink,])
        self.assertTrue(d.has_dirlinks)

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
        d = Directory(p)
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
        self.assertEqual(list(d.unwriteable_files),[])
        self.assertTrue(d.is_writeable)
        # Make unwriteable file by stripping permissions
        d = Directory(p)
        unwriteable_file = os.path.join(p,"ex1.txt")
        os.chmod(unwriteable_file,0o466)
        self.assertEqual(list(d.unwriteable_files),[unwriteable_file,])
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
        # Hard link should be detected
        d = Directory(p)
        self.assertEqual(sorted(list(d.hard_linked_files)),
                         sorted([hard_link_src,hard_link_dst]))
        self.assertTrue(d.has_hard_linked_files)

    def test_directory_symlink_to_hard_link(self):
        """
        Directory: check handling of symlink to hard link
        """
        # Build example dir without hard links or symlinks
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("ex2.txt",type="file",content="example 2")
        example_dir.create()
        p = example_dir.path
        # No hard links should be detected
        d = Directory(p)
        self.assertEqual(list(d.hard_linked_files),[])
        self.assertFalse(d.has_hard_linked_files)
        # No symlinks should be detected
        self.assertEqual(list(d.symlinks),[])
        self.assertFalse(d.has_symlinks)
        # Add hard link
        hard_link_src = os.path.join(p,"ex1.txt")
        hard_link_dst = os.path.join(p,"ex12.txt")
        os.link(hard_link_src,hard_link_dst)
        # Add symlink to the hard link
        symlink_dst = os.path.join(p,"symlink.txt")
        os.symlink(hard_link_src,symlink_dst)
        # Hard link should be detected
        d = Directory(p)
        self.assertEqual(sorted(list(d.hard_linked_files)),
                         sorted([hard_link_src,hard_link_dst]))
        self.assertTrue(d.has_hard_linked_files)
        # Symlink should be detected
        self.assertEqual(list(d.symlinks), [symlink_dst])
        self.assertTrue(d.has_symlinks)

    def test_directory_case_sensitive_filenames(self):
        """
        Directory: detect case-sensitive file names
        """
        # Build example dir without collisions
        example_dir = UnittestDir(os.path.join(self.wd,"example1"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex1.txt",type="file")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/ex1.txt",type="file")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir2/ex1.txt",type="file")
        example_dir.add("subdir2/ex2.txt",type="file")
        example_dir.create()
        p = example_dir.path
        d = Directory(p)
        self.assertEqual(sorted(list(d.case_sensitive_filenames)), [])
        self.assertFalse(d.has_case_sensitive_filenames)
        # Build example dir with collisions
        example_dir = UnittestDir(os.path.join(self.wd,"example2"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex1.txt",type="file")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/Ex2.txt",type="file")
        example_dir.add("SubDir1/ex1.txt",type="file")
        example_dir.add("SubDir1/ex2.txt",type="file")
        example_dir.create()
        p = example_dir.path
        d = Directory(p)
        self.assertEqual(sorted(list(d.case_sensitive_filenames)),
                         sorted([(os.path.join(p, "SubDir1"),
                                  os.path.join(p, "subdir1")),
                                 (os.path.join(p, "subdir1", "Ex2.txt"),
                                  os.path.join(p, "subdir1", "ex2.txt"))]))
        self.assertTrue(d.has_case_sensitive_filenames)

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

    def test_directory_verify_copy_with_symlink(self):
        """
        Directory: check 'verify_copy' method with symlink
        """
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./ex1.txt")
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

    def test_directory_verify_copy_with_external_symlink(self):
        """
        Directory: check 'verify_copy' method with external symlink
        """
        # External file
        with open(os.path.join(self.wd, "ex1.txt"), "wt") as fp:
            fp.write("external file")
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("external_symlink1",type="symlink",target="../ex1.txt")
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

    def test_directory_verify_copy_with_broken_symlink(self):
        """
        Directory: check 'verify_copy' method with broken symlink
        """
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("external_symlink1",type="symlink",
                        target="../doesnt_exist")
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

    def test_directory_verify_copy_with_symlink_follow_symlinks(self):
        """
        Directory: check 'verify_copy' method with symlink (follow symlinks)
        """
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./ex1.txt")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        dir1 = os.path.join(os.path.join(self.wd,"example1"))
        example_dir.create(dir1)
        dir2 = os.path.join(os.path.join(self.wd,"example2"))
        example_dir.create(dir2)
        # Check standard verification succeeds for identical dirs
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertTrue(d1.verify_copy(dir2))
        self.assertTrue(d2.verify_copy(dir1))
        # Replace symlink in one copy with the actual file
        os.remove(os.path.join(dir2, "symlink1"))
        shutil.copy2(os.path.join(dir2, "ex1.txt"),
                     os.path.join(dir2, "symlink1"))
        # Check standard verification now fails
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))
        # Check verification with 'follow_symlinks' is ok
        self.assertTrue(d1.verify_copy(dir2, follow_symlinks=True))
        self.assertTrue(d2.verify_copy(dir1, follow_symlinks=True))

    def test_directory_verify_copy_with_external_symlink_follow_symlinks(self):
        """
        Directory: check 'verify_copy' method with external symlink (follow symlinks)
        """
        # External file
        with open(os.path.join(self.wd, "ex1.txt"), "wt") as fp:
            fp.write("external file")
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("external_symlink1",type="symlink",target="../ex1.txt")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        dir1 = os.path.join(os.path.join(self.wd,"example1"))
        example_dir.create(dir1)
        dir2 = os.path.join(os.path.join(self.wd,"example2"))
        example_dir.create(dir2)
        # Check standard verification succeeds for identical dirs
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertTrue(d1.verify_copy(dir2))
        self.assertTrue(d2.verify_copy(dir1))
        # Replace symlink in one copy with the actual file
        os.remove(os.path.join(dir2, "external_symlink1"))
        shutil.copy2(os.path.join(self.wd, "ex1.txt"),
                     os.path.join(dir2, "external_symlink1"))
        # Check standard verification now fails
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))
        # Check verification with 'follow_symlinks' is ok
        self.assertTrue(d1.verify_copy(dir2, follow_symlinks=True))
        self.assertTrue(d2.verify_copy(dir1, follow_symlinks=True))

    def test_directory_verify_copy_with_broken_symlink_follow_symlinks(self):
        """
        Directory: check 'verify_copy' method with broken symlink (follow symlinks)
        """
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("external_symlink1",type="symlink",
                        target="../doesnt_exist")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        dir1 = os.path.join(os.path.join(self.wd,"example1"))
        example_dir.create(dir1)
        dir2 = os.path.join(os.path.join(self.wd,"example2"))
        example_dir.create(dir2)
        # Check verification without follow symlinks
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertTrue(d1.verify_copy(dir2))
        self.assertTrue(d2.verify_copy(dir1))
        # Check verification with follow symlinks
        self.assertFalse(d1.verify_copy(dir2, follow_symlinks=True))
        self.assertFalse(d2.verify_copy(dir1, follow_symlinks=True))

    def test_directory_verify_copy_with_broken_symlink_placeholder(self):
        """
        Directory: check 'verify_copy' method with broken symlink placeholder
        """
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./ex1.txt")
        example_dir.add("external_symlink1",type="symlink",
                        target="../doesnt_exist")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        dir1 = os.path.join(os.path.join(self.wd,"example1"))
        example_dir.create(dir1)
        dir2 = os.path.join(os.path.join(self.wd,"example2"))
        example_dir.create(dir2)
        # Check standard verification works
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertTrue(d1.verify_copy(dir2))
        self.assertTrue(d2.verify_copy(dir1))
        # Replace broken symlink in one copy with placeholder file
        os.remove(os.path.join(dir2, "external_symlink1"))
        with open(os.path.join(dir2, "external_symlink1"), "wt") as fp:
            fp.write(f"../doesnt_exist")
        # Check standard verification now fails
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))
        # Check verification with broken symlinks placeholders
        self.assertTrue(d1.verify_copy(dir2,
                                       broken_symlinks_placeholders=True))
        # Verification still fails the other way around
        # (because a regular file cannot match a symlink)
        self.assertFalse(d2.verify_copy(dir1,
                                        broken_symlinks_placeholders=True))
        # Replace working symlink in one copy with target file contents
        os.remove(os.path.join(dir2, "symlink1"))
        with open(os.path.join(dir2, "symlink1"), "wt") as fp:
            fp.write("example 1")
        # Check verification using follow symlinks
        self.assertFalse(d1.verify_copy(dir2,
                                        follow_symlinks=True))
        self.assertTrue(d1.verify_copy(dir2,
                                       follow_symlinks=True,
                                       broken_symlinks_placeholders=True))

    def test_directory_verify_copy_with_symlink_loop_placeholder(self):
        """
        Directory: check 'verify_copy' method with placeholder for unresolvable symlink loop
        """
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./symlink1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        dir1 = os.path.join(os.path.join(self.wd,"example1"))
        example_dir.create(dir1)
        dir2 = os.path.join(os.path.join(self.wd,"example2"))
        example_dir.create(dir2)
        # Check standard verification works
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertTrue(d1.verify_copy(dir2))
        self.assertTrue(d2.verify_copy(dir1))
        # Replace symlink loop in one copy with placeholder file
        os.remove(os.path.join(dir2, "symlink1"))
        with open(os.path.join(dir2, "symlink1"), "wt") as fp:
            fp.write(f"./symlink1")
        # Check standard verification now fails
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))
        # Check verification with broken symlinks placeholders
        self.assertTrue(d1.verify_copy(dir2,
                                       broken_symlinks_placeholders=True))
        # Verification still fails the other way around
        # (because a regular file cannot match a symlink)
        self.assertFalse(d2.verify_copy(dir1,
                                        broken_symlinks_placeholders=True))

    def test_directory_verify_copy_with_unresolvable_symlink_loop(self):
        """
        Directory: check 'verify_copy' method with unresolvable symlink loop
        """
        # Build identical example dirs
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("symlink1",type="symlink",target="./symlink1")
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

    def test_directory_verify_copy_missing_file(self):
        """
        Directory: check 'verify_copy' method for missing file
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
        # Remove a file from one of the copies
        os.remove(os.path.join(self.wd, "example1", "subdir1", "ex2.txt"))
        # Check verification when identical
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))
        # Add a file to second directory
        with open(os.path.join(dir2,"extra.txt"),'wt') as fp:
            fp.write("extra stuff")
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))

    def test_directory_verify_copy_missing_directory(self):
        """
        Directory: check 'verify_copy' method for missing directory
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
        # Add a subdir to one of the copies
        os.mkdir(os.path.join(self.wd, "example1", "subdir2"))
        # Check verification when identical
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))
        # Add a file to second directory
        with open(os.path.join(dir2,"extra.txt"),'wt') as fp:
            fp.write("extra stuff")
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))

    def test_directory_verify_copy_symlink_differs(self):
        """
        Directory: check 'verify_copy' method for differing symlink
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
        # Make differing symlinks
        os.symlink("ex1.txt", os.path.join(self.wd, "example1", "symlink"))
        os.symlink("subdir1/ex2.txt",
                   os.path.join(self.wd, "example2", "symlink"))
        # Check verification when identical
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))
        # Add a file to second directory
        with open(os.path.join(dir2,"extra.txt"),'wt') as fp:
            fp.write("extra stuff")
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))

    def test_directory_verify_copy_ignore_paths(self):
        """
        Directory: check 'verify_copy' method ignoring specified files
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
        # Add extra stuff to second directory
        with open(os.path.join(dir2,"extra1.txt"),'wt') as fp:
            fp.write("extra stuff")
        os.mkdir(os.path.join(dir2, "extra_dir"))
        with open(os.path.join(dir2, "extra_dir", "extra2.txt"),'wt') as fp:
            fp.write("more extra stuff")
        # Default verification fails
        d1 = Directory(dir1)
        d2 = Directory(dir2)
        self.assertFalse(d1.verify_copy(dir2))
        self.assertFalse(d2.verify_copy(dir1))
        # Verfication explicitly ignoring extra files
        self.assertTrue(d1.verify_copy(dir2, ignore_paths=("extra1.txt",
                                                           "extra_dir",
                                                           "extra_dir/*")))
        self.assertTrue(d2.verify_copy(dir1, ignore_paths=("extra1.txt",
                                                           "extra_dir",
                                                           "extra_dir/*")))

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

    def test_directory_walk_dirlinks(self):
        """
        Directory: check 'walk' method with dirlinks
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        example_dir.add("subdir2",type="symlink",target="./subdir1")
        example_dir.create()
        p = example_dir.path
        # Check walk method
        d = Directory(p)
        self.assertEqual(sorted(list(d.walk())),
                         [os.path.join(p,f)
                          for f in ("ex1.txt",
                                    "subdir1",
                                    "subdir1/ex2.txt",
                                    "subdir1/subdir12",
                                    "subdir1/subdir12/ex3.txt",
                                    "subdir2")])

    def test_directory_walk_follow_dirlinks(self):
        """
        Directory: check 'walk' method follows dirlinks
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        example_dir.add("subdir2",type="symlink",target="./subdir1")
        example_dir.create()
        p = example_dir.path
        # Check walk method
        d = Directory(p)
        self.assertEqual(sorted(list(d.walk(followlinks=True))),
                         [os.path.join(p,f)
                          for f in ("ex1.txt",
                                    "subdir1",
                                    "subdir1/ex2.txt",
                                    "subdir1/subdir12",
                                    "subdir1/subdir12/ex3.txt",
                                    "subdir2",
                                    "subdir2/ex2.txt",
                                    "subdir2/subdir12",
                                    "subdir2/subdir12/ex3.txt")])

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
        example_archive.add("ARCHIVE_METADATA/archive_checksums.md5",
                            type="file",
                            content="f210d02b4a294ec38c6ed82b92a73c44  example.tar.gz\n")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "ArchiveDirectory",
  "subarchives": [
    "example.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_README.txt",type="file")
        example_archive.add("ARCHIVE_FILELIST.txt",type="file")
        example_archive.add("ARCHIVE_TREE.txt",type="file")
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

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
        example_archive.add("ARCHIVE_METADATA/archive_checksums.md5",
                            type="file",
                            content="""ea40b4706e9d97459173ddba2cc8f673  subdir1.tar.gz
21ab03a93bb341292ca281bf7f9d7176  subdir2.tar.gz
a0b67a19eabb5b96f97a8694e4d8cd9e  miscellaneous.tar.gz
""")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "ArchiveDirectory",
  "subarchives": [
    "subdir1.tar.gz",
    "subdir2.tar.gz",
    "miscellaneous.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_README.txt",type="file")
        example_archive.add("ARCHIVE_FILELIST.txt",type="file")
        example_archive.add("ARCHIVE_TREE.txt",type="file")
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

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
        example_archive.add("ARCHIVE_METADATA/archive_checksums.md5",
                            type="file",
                            content="""f299d91fe1d73319e4daa11dc3a12a33  extra_file.txt
ea40b4706e9d97459173ddba2cc8f673  subdir1.tar.gz
21ab03a93bb341292ca281bf7f9d7176  subdir2.tar.gz
a0b67a19eabb5b96f97a8694e4d8cd9e  miscellaneous.tar.gz
""")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "ArchiveDirectory",
  "subarchives": [
    "subdir1.tar.gz",
    "subdir2.tar.gz",
    "miscellaneous.tar.gz"
  ],
  "files": [
    "extra_file.txt"
  ],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_README.txt",type="file")
        example_archive.add("ARCHIVE_FILELIST.txt",type="file")
        example_archive.add("ARCHIVE_TREE.txt",type="file")
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(name="extra*.txt")]),
                         ["example/extra_file.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="*/extra_file.txt",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"extra_file.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

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
        example_archive.add("ARCHIVE_METADATA/archive_checksums.md5",
                            type="file",
                            content='\n'.join(["%s  %s" % (m[1],m[0])
                                               for m in md5s]))
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "ArchiveDirectory",
  "subarchives": [
    "example.00.tar.gz",
    "example.01.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": true,
  "volume_size": "250M",
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_README.txt",type="file")
        example_archive.add("ARCHIVE_FILELIST.txt",type="file")
        example_archive.add("ARCHIVE_TREE.txt",type="file")
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/subdir1/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="example/subdir1/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","subdir1","ex1.txt")))

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
        example_archive.add("ARCHIVE_METADATA/archive_checksums.md5",
                            type="file",
                            content='\n'.join(["%s  %s" % (m[1],m[0])
                                               for m in md5s]))
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "ArchiveDirectory",
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
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": true,
  "volume_size": "250M",
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_README.txt",type="file")
        example_archive.add("ARCHIVE_FILELIST.txt",type="file")
        example_archive.add("ARCHIVE_TREE.txt",type="file")
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

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
        example_archive.add("ARCHIVE_METADATA/archive_checksums.md5",
                            type="file",
                            content='\n'.join(["%s  %s" % (m[1],m[0])
                                               for m in md5s]))
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "ArchiveDirectory",
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
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": true,
  "volume_size": "250M",
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_README.txt",type="file")
        example_archive.add("ARCHIVE_FILELIST.txt",type="file")
        example_archive.add("ARCHIVE_TREE.txt",type="file")
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(name="extra*.txt")]),
                         ["example/extra_file.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="*/extra_file.txt",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"extra_file.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

    def test_archivedirectory_with_external_symlink(self):
        """
        ArchiveDirectory: archive with external symlink
        """
        # Build example archive dir
        example_archive = UnittestDir(
            os.path.join(self.wd,
                         "example_external_symlinks.archive"))
        example_archive.add("example_external_symlinks.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sICPGH5GQA/2V4YW1wbGVfZXh0ZXJuYWxfc3ltbGlua3MudGFyAO3bzW7aQBiFYda9Cq5gmPnmz7Oo1GWXuYPIaVyV1qQREMm9+9qJUn4qaijEDpr32YAwwmYx58DMWM3U7NNN2XyuyvtqOXkT+sWhR62t2zzvXjfGeZlMm7e5nF1Pq3W5bE9/7ufsf7krIcV0sZ4vqo8mJAmp8Ckp64pYePdh7GvD26uacvFYV7dVs66WD2V9u/q1qOcPP1azqjFq3awvcI5uPITwPMZN9Hr78YXZH//RtIengwyi1/H/+P3un+/rO36l4/+mLr9U337Wbfgz3jOk6H/6f6v/rXglRQjaWPIgA4f7f/V0dz9fyuz8c3TjIUZ/uP+13u9/iWYy9eeful/m/U/+k//b+S8mKO2sDdqT/xnoy38zVv5r8n8I5D/5v53/2otKSVwU5v9y0Jf/dqz8F/J/CO8j/+3f+W/I/yFI3Mt/V6jkxSV+/mehf/7n/HWgbjyctP4j7a8QYf1nCKz/5I3+p//p/3wd0/8yRv9b+n8I9H/e3kf/M/87FvZ/5O2Y/t89cvpsQDceYozHz/9KezRMpqLadFKbC/g6r6sLbUndyLz/yX/yf2f/hy6UDdEZF8n/DPTv//jv2P/j9Py3Jjzn/wVvQjiE/Cf/yf/X/I8pdfnvYkzkfw7683+k9T/D/N8QmP/LG/1P/++s/4lRRorgTSAPMnBM/4+y/sf+n0HQ/3mj/+l/7v/IV//9HyP9/2f/zyDo/7zR//Q//Z+vY/p/lP//jv4fAv0PAAAAAAAAAAAAAAAAXK/f57i5aQB4AAA='))
        example_archive.add("example_external_symlinks.md5",
                            type="file",
                            content="""a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir2/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir2/ex2.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir1/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir1/ex2.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir3/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir3/ex2.txt
""")
        example_archive.add("ARCHIVE_METADATA/archive_checksums.md5",
                            type="file",
                            content="cdf7fcdf08b0afa29f1458b10e317861  example_external_symlinks.tar.gz\n")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example_external_symlinks",
  "source": "/original/path/to/example_external_symlinks",
  "source_date": "2019-11-27 17:19:02",
  "type": "ArchiveDirectory",
  "subarchives": [
    "example_external_symlinks.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_METADATA/symlinks",type="file",
                            content="""example_external_symlinks/subdir2/external_symlink1.txt	example_external_symlinks.tar.gz
example_external_symlinks/subdir1/symlink1.txt	example_external_symlinks.tar.gz
""")
        example_archive.add("ARCHIVE_README.txt",type="file")
        example_archive.add("ARCHIVE_FILELIST.txt",type="file")
        example_archive.add("ARCHIVE_TREE.txt",type="file")
        example_archive.create()
        p = example_archive.path
        # Add an external file
        external_file = os.path.join(self.wd,"external_file")
        with open(external_file,'wt') as fp:
            fp.write("external content")
        # Expected contents
        expected = ('example_external_symlinks/ex1.txt',
                    'example_external_symlinks/subdir1',
                    'example_external_symlinks/subdir1/ex1.txt',
                    'example_external_symlinks/subdir1/ex2.txt',
                    'example_external_symlinks/subdir1/symlink1.txt',
                    'example_external_symlinks/subdir2',
                    'example_external_symlinks/subdir2/ex1.txt',
                    'example_external_symlinks/subdir2/ex2.txt',
                    'example_external_symlinks/subdir2/external_symlink1.txt',
                    'example_external_symlinks/subdir3',
                    'example_external_symlinks/subdir3/ex1.txt',
                    'example_external_symlinks/subdir3/ex2.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example_external_symlinks")
        self.assertEqual(metadata['subarchives'],
                         ["example_external_symlinks.tar.gz"])
        self.assertEqual(metadata['files'],[])
        self.assertEqual(metadata['multi_volume'],False)
        self.assertEqual(metadata['volume_size'],None)
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Search for symlinks
        self.assertEqual(sorted([x.path for x in a.search(name="*symlink1.txt")]),
                         ["example_external_symlinks/subdir1/symlink1.txt",
                          "example_external_symlinks/subdir2/external_symlink1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example_external_symlinks/subdir*/*symlink1.txt")]),
                         ["example_external_symlinks/subdir1/symlink1.txt",
                          "example_external_symlinks/subdir2/external_symlink1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example_external_symlinks/ex1.txt",
                          "example_external_symlinks/subdir1/ex1.txt",
                          "example_external_symlinks/subdir2/ex1.txt",
                          "example_external_symlinks/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(
            os.path.join(self.wd,"example_external_symlinks")))
        self.assertEqual(
            os.path.getmtime(os.path.join(self.wd,"example_external_symlinks")),
            os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(
                os.path.join(self.wd,"example_external_symlinks")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract internal symlink
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example_external_symlinks/subdir1/symlink1.*",
                        extract_dir=extract_dir)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,"symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,"symlink1.txt")),
                         "./ex1.txt")
        a.extract_files(name="example_external_symlinks/subdir1/symlink1.*",
                        extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,
                         "example_external_symlinks",
                         "subdir1",
                         "symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,
                         "example_external_symlinks",
                         "subdir1",
                         "symlink1.txt")),
                         "./ex1.txt")
        # Extract external symlink
        a.extract_files(
            name="example_external_symlinks/subdir2/external_symlink1.*",
            extract_dir=extract_dir)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,"external_symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,"external_symlink1.txt")),
                         "../../external_file.txt")
        a.extract_files(
            name="example_external_symlinks/subdir2/external_symlink1.*",
            extract_dir=extract_dir,
            include_path=True)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,
                         "example_external_symlinks",
                         "subdir2",
                         "external_symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,
                         "example_external_symlinks",
                         "subdir2",
                         "external_symlink1.txt")),
                         "../../external_file.txt")

    def test_archivedirectory_with_broken_symlink(self):
        """
        ArchiveDirectory: archive with broken symlink
        """
        # Build example archive dir
        example_archive = UnittestDir(os.path.join(
            self.wd,
            "example_broken_symlinks.archive"))
        example_archive.add("example_broken_symlinks.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sICCqa5GQA/2V4YW1wbGVfYnJva2VuX3N5bWxpbmtzLnRhcgDt281u2kAYhWHWvQpfwTDzzZ9nUanLLnMHkWkslQaSCIhE7z44CSrQgJvG2EHzPhsiEsWw+M6BmbEaq/G3q2r9va5u6sXoLPSLY49aW/fn5+Z5Y5yXUbE+z8vZ97hcVYvN5T/6fw7f3IWQspivpvP6qwlJQip9Ssq6MpbefRn6teH86nU1f5jV15PF/W19d738PZ9N726X43pt1Gq96uQazTyE8DzjJnq9+/jCHM5/CDqMil6GaDv/D78mJ/+u7fcXOv9Xs+pH/fN+tgl/5j1Div6n/7f9H7UVWyrjy3IT2ORBBo71//JxcjNdyLiLazTzEKM/3v9aH/Z/lDgqfBcXb5N5/5P/5P/u9z8xQWlnbdCe/M/A6fw3w+V/IP/7QP6T/7v5r72olMRFYf0vB6fz3w6W/1aT/334HPlv/85/Q/73QeJB/rtSJS8u8fE/C23rP13sAzXz8K79H9k0gGb/pw/s/+SN/qf/6f98tfe/DNP/hv7vA/2ft8/R/6z/DoXzH3lr6//95/9vLaCZhxjjv6//ijMhjgpRm48ftrNjqG/LvP/Jf/J/7/yHLpUN0RkXyf8MtJ3/+FDwv3p//ksQ95r/3d2G8Dbyn/wn/7f5H1Nq8t/FmMj/HLTl/1D7fz6y/tcH1v/yRv/T/3v7f2KUkTJ4w/pfDtr7f6D9P87/9IL+zxv9T/9z/0e+2u7/GOz8L+d/ekH/543+p//p/3y19/9A3/+F/u8D/Q8AAAAAAAAAAAAAAABcridJPIFaAHgAAA=='))
        example_archive.add("example_broken_symlinks.md5",
                            type="file",
                            content="""a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir2/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir2/ex2.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir1/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir1/ex2.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir3/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir3/ex2.txt
""")
        example_archive.add("ARCHIVE_METADATA/archive_checksums.md5",
                            type="file",
                            content="a36ee4df21f4f6f35e1ea92282e92b22  example_broken_symlinks.tar.gz\n")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",type="file",
                            content="""{
  "name": "example_broken_symlinks",
  "source": "/original/path/to/example_broken_symlinks",
  "source_date": "2019-11-27 17:19:02",
  "type": "ArchiveDirectory",
  "subarchives": [
    "example_broken_symlinks.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_METADATA/symlinks",type="file",
                            content="""example_broken_symlinks/subdir2/broken_symlink1.txt	example_broken_symlinks.tar.gz
example_broken_symlinks/subdir1/symlink1.txt	example_broken_symlinks.tar.gz
""")
        example_archive.add("ARCHIVE_README.txt",type="file")
        example_archive.add("ARCHIVE_FILELIST.txt",type="file")
        example_archive.add("ARCHIVE_TREE.txt",type="file")
        example_archive.create()
        p = example_archive.path
        # Expected contents
        expected = ('example_broken_symlinks/ex1.txt',
                    'example_broken_symlinks/subdir1',
                    'example_broken_symlinks/subdir1/ex1.txt',
                    'example_broken_symlinks/subdir1/ex2.txt',
                    'example_broken_symlinks/subdir1/symlink1.txt',
                    'example_broken_symlinks/subdir2',
                    'example_broken_symlinks/subdir2/ex1.txt',
                    'example_broken_symlinks/subdir2/ex2.txt',
                    'example_broken_symlinks/subdir2/broken_symlink1.txt',
                    'example_broken_symlinks/subdir3',
                    'example_broken_symlinks/subdir3/ex1.txt',
                    'example_broken_symlinks/subdir3/ex2.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example_broken_symlinks")
        self.assertEqual(metadata['subarchives'],
                         ["example_broken_symlinks.tar.gz"])
        self.assertEqual(metadata['files'],[])
        self.assertEqual(metadata['multi_volume'],False)
        self.assertEqual(metadata['volume_size'],None)
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Search for symlinks
        self.assertEqual(sorted([x.path for x in a.search(name="*symlink1.txt")]),
                         ["example_broken_symlinks/subdir1/symlink1.txt",
                          "example_broken_symlinks/subdir2/broken_symlink1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example_broken_symlinks/subdir*/*symlink1.txt")]),
                         ["example_broken_symlinks/subdir1/symlink1.txt",
                          "example_broken_symlinks/subdir2/broken_symlink1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example_broken_symlinks/ex1.txt",
                          "example_broken_symlinks/subdir1/ex1.txt",
                          "example_broken_symlinks/subdir2/ex1.txt",
                          "example_broken_symlinks/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(
            self.wd,"example_broken_symlinks")))
        self.assertEqual(os.path.getmtime(os.path.join(
            self.wd,"example_broken_symlinks")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(
                os.path.join(self.wd,"example_broken_symlinks")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract "working" symlink (will be broken)
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example_broken_symlinks/subdir1/symlink1.*",
                        extract_dir=extract_dir)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,"symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,"symlink1.txt")),
                         "./ex1.txt")
        a.extract_files(name="example_broken_symlinks/subdir1/symlink1.*",
                        extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,
                         "example_broken_symlinks",
                         "subdir1",
                         "symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,
                         "example_broken_symlinks",
                         "subdir1",
                         "symlink1.txt")),
                         "./ex1.txt")
        # Extract broken symlink
        a.extract_files(
            name="example_broken_symlinks/subdir2/broken_symlink1.*",
            extract_dir=extract_dir)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,"broken_symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,"broken_symlink1.txt")),
                         "./ex3.txt")
        a.extract_files(
            name="example_broken_symlinks/subdir2/broken_symlink1.*",
            extract_dir=extract_dir,
            include_path=True)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,
                         "example_broken_symlinks",
                         "subdir2",
                         "broken_symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,
                         "example_broken_symlinks",
                         "subdir2",
                         "broken_symlink1.txt")),
                         "./ex3.txt")

    def test_archivedirectory_unpack_non_standard_name(self):
        """
        ArchiveDirectory: unpack archive with non-standard name
        """
        # Build example archive dir with a non-standard name
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "example.archived"))
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
        example_archive.add("ARCHIVE_METADATA/archive_checksums.md5",
                            type="file",
                            content="f210d02b4a294ec38c6ed82b92a73c44  example.tar.gz\n")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "ArchiveDirectory",
  "subarchives": [
    "example.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_README.txt",type="file")
        example_archive.add("ARCHIVE_FILELIST.txt",type="file")
        example_archive.add("ARCHIVE_TREE.txt",type="file")
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack (& check no extra artefacts are created)
        self.assertFalse(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.listdir(self.wd), ["example.archived"])
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.listdir(self.wd), ["example.archived", "example"])
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))


class TestLegacyArchiveDirectory(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestLegacyArchiveDirectory')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_legacy_archivedirectory_single_subarchive(self):
        """
        ArchiveDirectory (legacy): single subarchive
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
  "source_date": "2019-11-27 17:19:02",
  "subarchives": [
    "example.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

    def test_legacy_archivedirectory_multiple_subarchives(self):
        """
        ArchiveDirectory (legacy): multiple subarchives
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
  "creation_date": "2023-06-16 09:58:39",
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

    def test_legacy_archivedirectory_multiple_subarchives_and_file(self):
        """
        ArchiveDirectory (legacy): multiple subarchives and extra file
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
  "creation_date": "2023-06-16 09:58:39",
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(name="extra*.txt")]),
                         ["example/extra_file.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="*/extra_file.txt",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"extra_file.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

    def test_legacy_archivedirectory_multi_volume_single_subarchive(self):
        """
        ArchiveDirectory (legacy): single multi-volume subarchive
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
  "creation_date": "2023-06-16 09:58:39",
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/subdir1/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="example/subdir1/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","subdir1","ex1.txt")))

    def test_legacy_archivedirectory_multi_volume_multiple_subarchives(self):
        """
        ArchiveDirectory (legacy): multiple multi-volume subarchives
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
  "creation_date": "2023-06-16 09:58:39",
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

    def test_legacy_archivedirectory_multi_volume_multiple_subarchives_and_file(self):
        """
        ArchiveDirectory (legacy): multiple multi-volume subarchives and extra file
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
  "creation_date": "2023-06-16 09:58:39",
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
        # Search for items
        self.assertEqual(sorted([x.path for x in a.search(name="ex1.*")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(name="extra*.txt")]),
                         ["example/extra_file.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example/subdir*/ex1.txt")]),
                         ["example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example/ex1.txt",
                          "example/subdir1/ex1.txt",
                          "example/subdir2/ex1.txt",
                          "example/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(self.wd,"example")))
        self.assertEqual(os.path.getmtime(os.path.join(self.wd,"example")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(os.path.join(self.wd,"example")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract items
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"ex1.txt")))
        a.extract_files(name="*/extra_file.txt",extract_dir=extract_dir)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"extra_file.txt")))
        a.extract_files(name="example/ex1.*",extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.exists(
            os.path.join(extract_dir,"example","ex1.txt")))

    def test_legacy_archivedirectory_with_external_symlink(self):
        """
        ArchiveDirectory (legacy): archive with external symlink
        """
        # Build example archive dir
        example_archive = UnittestDir(
            os.path.join(self.wd,
                         "example_external_symlinks.archive"))
        example_archive.add("example_external_symlinks.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sICPGH5GQA/2V4YW1wbGVfZXh0ZXJuYWxfc3ltbGlua3MudGFyAO3bzW7aQBiFYda9Cq5gmPnmz7Oo1GWXuYPIaVyV1qQREMm9+9qJUn4qaijEDpr32YAwwmYx58DMWM3U7NNN2XyuyvtqOXkT+sWhR62t2zzvXjfGeZlMm7e5nF1Pq3W5bE9/7ufsf7krIcV0sZ4vqo8mJAmp8Ckp64pYePdh7GvD26uacvFYV7dVs66WD2V9u/q1qOcPP1azqjFq3awvcI5uPITwPMZN9Hr78YXZH//RtIengwyi1/H/+P3un+/rO36l4/+mLr9U337Wbfgz3jOk6H/6f6v/rXglRQjaWPIgA4f7f/V0dz9fyuz8c3TjIUZ/uP+13u9/iWYy9eeful/m/U/+k//b+S8mKO2sDdqT/xnoy38zVv5r8n8I5D/5v53/2otKSVwU5v9y0Jf/dqz8F/J/CO8j/+3f+W/I/yFI3Mt/V6jkxSV+/mehf/7n/HWgbjyctP4j7a8QYf1nCKz/5I3+p//p/3wd0/8yRv9b+n8I9H/e3kf/M/87FvZ/5O2Y/t89cvpsQDceYozHz/9KezRMpqLadFKbC/g6r6sLbUndyLz/yX/yf2f/hy6UDdEZF8n/DPTv//jv2P/j9Py3Jjzn/wVvQjiE/Cf/yf/X/I8pdfnvYkzkfw7683+k9T/D/N8QmP/LG/1P/++s/4lRRorgTSAPMnBM/4+y/sf+n0HQ/3mj/+l/7v/IV//9HyP9/2f/zyDo/7zR//Q//Z+vY/p/lP//jv4fAv0PAAAAAAAAAAAAAAAAXK/f57i5aQB4AAA='))
        example_archive.add("example_external_symlinks.md5",
                            type="file",
                            content="""a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir2/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir2/ex2.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir1/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir1/ex2.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir3/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_external_symlinks/subdir3/ex2.txt
""")
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content="cdf7fcdf08b0afa29f1458b10e317861  example_external_symlinks.tar.gz\n")
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example_external_symlinks",
  "source": "/original/path/to/example_external_symlinks",
  "subarchives": [
    "example_external_symlinks.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add(".ngsarchiver/manifest.txt",type="file")
        example_archive.add(".ngsarchiver/symlinks.txt",type="file",
                            content="""example_external_symlinks/subdir2/external_symlink1.txt	example_external_symlinks.tar.gz
example_external_symlinks/subdir1/symlink1.txt	example_external_symlinks.tar.gz
""")
        example_archive.create()
        p = example_archive.path
        # Add an external file
        external_file = os.path.join(self.wd,"external_file")
        with open(external_file,'wt') as fp:
            fp.write("external content")
        # Expected contents
        expected = ('example_external_symlinks/ex1.txt',
                    'example_external_symlinks/subdir1',
                    'example_external_symlinks/subdir1/ex1.txt',
                    'example_external_symlinks/subdir1/ex2.txt',
                    'example_external_symlinks/subdir1/symlink1.txt',
                    'example_external_symlinks/subdir2',
                    'example_external_symlinks/subdir2/ex1.txt',
                    'example_external_symlinks/subdir2/ex2.txt',
                    'example_external_symlinks/subdir2/external_symlink1.txt',
                    'example_external_symlinks/subdir3',
                    'example_external_symlinks/subdir3/ex1.txt',
                    'example_external_symlinks/subdir3/ex2.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example_external_symlinks")
        self.assertEqual(metadata['subarchives'],
                         ["example_external_symlinks.tar.gz"])
        self.assertEqual(metadata['files'],[])
        self.assertEqual(metadata['multi_volume'],False)
        self.assertEqual(metadata['volume_size'],None)
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Search for symlinks
        self.assertEqual(sorted([x.path for x in a.search(name="*symlink1.txt")]),
                         ["example_external_symlinks/subdir1/symlink1.txt",
                          "example_external_symlinks/subdir2/external_symlink1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example_external_symlinks/subdir*/*symlink1.txt")]),
                         ["example_external_symlinks/subdir1/symlink1.txt",
                          "example_external_symlinks/subdir2/external_symlink1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example_external_symlinks/ex1.txt",
                          "example_external_symlinks/subdir1/ex1.txt",
                          "example_external_symlinks/subdir2/ex1.txt",
                          "example_external_symlinks/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(
            os.path.join(self.wd,"example_external_symlinks")))
        self.assertEqual(
            os.path.getmtime(os.path.join(self.wd,"example_external_symlinks")),
            os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(
                os.path.join(self.wd,"example_external_symlinks")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract internal symlink
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example_external_symlinks/subdir1/symlink1.*",
                        extract_dir=extract_dir)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,"symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,"symlink1.txt")),
                         "./ex1.txt")
        a.extract_files(name="example_external_symlinks/subdir1/symlink1.*",
                        extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,
                         "example_external_symlinks",
                         "subdir1",
                         "symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,
                         "example_external_symlinks",
                         "subdir1",
                         "symlink1.txt")),
                         "./ex1.txt")
        # Extract external symlink
        a.extract_files(
            name="example_external_symlinks/subdir2/external_symlink1.*",
            extract_dir=extract_dir)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,"external_symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,"external_symlink1.txt")),
                         "../../external_file.txt")
        a.extract_files(
            name="example_external_symlinks/subdir2/external_symlink1.*",
            extract_dir=extract_dir,
            include_path=True)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,
                         "example_external_symlinks",
                         "subdir2",
                         "external_symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,
                         "example_external_symlinks",
                         "subdir2",
                         "external_symlink1.txt")),
                         "../../external_file.txt")

    def test_legacy_archivedirectory_with_broken_symlink(self):
        """
        ArchiveDirectory (legacy): archive with broken symlink
        """
        # Build example archive dir
        example_archive = UnittestDir(os.path.join(
            self.wd,
            "example_broken_symlinks.archive"))
        example_archive.add("example_broken_symlinks.tar.gz",
                            type="binary",
                            content=base64.b64decode(b'H4sICCqa5GQA/2V4YW1wbGVfYnJva2VuX3N5bWxpbmtzLnRhcgDt281u2kAYhWHWvQpfwTDzzZ9nUanLLnMHkWkslQaSCIhE7z44CSrQgJvG2EHzPhsiEsWw+M6BmbEaq/G3q2r9va5u6sXoLPSLY49aW/fn5+Z5Y5yXUbE+z8vZ97hcVYvN5T/6fw7f3IWQspivpvP6qwlJQip9Ssq6MpbefRn6teH86nU1f5jV15PF/W19d738PZ9N726X43pt1Gq96uQazTyE8DzjJnq9+/jCHM5/CDqMil6GaDv/D78mJ/+u7fcXOv9Xs+pH/fN+tgl/5j1Div6n/7f9H7UVWyrjy3IT2ORBBo71//JxcjNdyLiLazTzEKM/3v9aH/Z/lDgqfBcXb5N5/5P/5P/u9z8xQWlnbdCe/M/A6fw3w+V/IP/7QP6T/7v5r72olMRFYf0vB6fz3w6W/1aT/334HPlv/85/Q/73QeJB/rtSJS8u8fE/C23rP13sAzXz8K79H9k0gGb/pw/s/+SN/qf/6f98tfe/DNP/hv7vA/2ft8/R/6z/DoXzH3lr6//95/9vLaCZhxjjv6//ijMhjgpRm48ftrNjqG/LvP/Jf/J/7/yHLpUN0RkXyf8MtJ3/+FDwv3p//ksQ95r/3d2G8Dbyn/wn/7f5H1Nq8t/FmMj/HLTl/1D7fz6y/tcH1v/yRv/T/3v7f2KUkTJ4w/pfDtr7f6D9P87/9IL+zxv9T/9z/0e+2u7/GOz8L+d/ekH/543+p//p/3y19/9A3/+F/u8D/Q8AAAAAAAAAAAAAAABcridJPIFaAHgAAA=='))
        example_archive.add("example_broken_symlinks.md5",
                            type="file",
                            content="""a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir2/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir2/ex2.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir1/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir1/ex2.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir3/ex1.txt
a03dcb0295d903ee194ccb117b41f870  example_broken_symlinks/subdir3/ex2.txt
""")
        example_archive.add(".ngsarchiver/archive.md5",
                            type="file",
                            content="a36ee4df21f4f6f35e1ea92282e92b22  example_broken_symlinks.tar.gz\n")
        example_archive.add(".ngsarchiver/archive_metadata.json",type="file",
                            content="""{
  "name": "example_broken_symlinks",
  "source": "/original/path/to/example_broken_symlinks",
  "subarchives": [
    "example_broken_symlinks.tar.gz"
  ],
  "files": [],
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "multi_volume": false,
  "volume_size": null,
  "compression_level": 6,
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.add(".ngsarchiver/manifest.txt",type="file")
        example_archive.add(".ngsarchiver/symlinks.txt",type="file",
                            content="""example_broken_symlinks/subdir2/broken_symlink1.txt	example_broken_symlinks.tar.gz
example_broken_symlinks/subdir1/symlink1.txt	example_broken_symlinks.tar.gz
""")
        example_archive.create()
        p = example_archive.path
        # Expected contents
        expected = ('example_broken_symlinks/ex1.txt',
                    'example_broken_symlinks/subdir1',
                    'example_broken_symlinks/subdir1/ex1.txt',
                    'example_broken_symlinks/subdir1/ex2.txt',
                    'example_broken_symlinks/subdir1/symlink1.txt',
                    'example_broken_symlinks/subdir2',
                    'example_broken_symlinks/subdir2/ex1.txt',
                    'example_broken_symlinks/subdir2/ex2.txt',
                    'example_broken_symlinks/subdir2/broken_symlink1.txt',
                    'example_broken_symlinks/subdir3',
                    'example_broken_symlinks/subdir3/ex1.txt',
                    'example_broken_symlinks/subdir3/ex2.txt',)
        # Check example loads as ArchiveDirectory
        a = ArchiveDirectory(p)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        # Check subset of metadata
        metadata = a.archive_metadata
        self.assertEqual(metadata['name'],"example_broken_symlinks")
        self.assertEqual(metadata['subarchives'],
                         ["example_broken_symlinks.tar.gz"])
        self.assertEqual(metadata['files'],[])
        self.assertEqual(metadata['multi_volume'],False)
        self.assertEqual(metadata['volume_size'],None)
        # List contents
        for item in a.list():
            self.assertTrue(item.path in expected,
                            "%s: unexpected item" % item.path)
        # Search for symlinks
        self.assertEqual(sorted([x.path for x in a.search(name="*symlink1.txt")]),
                         ["example_broken_symlinks/subdir1/symlink1.txt",
                          "example_broken_symlinks/subdir2/broken_symlink1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            path="example_broken_symlinks/subdir*/*symlink1.txt")]),
                         ["example_broken_symlinks/subdir1/symlink1.txt",
                          "example_broken_symlinks/subdir2/broken_symlink1.txt"])
        self.assertEqual(sorted([x.path for x in a.search(
            name="ex1.*",
            path="*/ex1.txt")]),
                         ["example_broken_symlinks/ex1.txt",
                          "example_broken_symlinks/subdir1/ex1.txt",
                          "example_broken_symlinks/subdir2/ex1.txt",
                          "example_broken_symlinks/subdir3/ex1.txt"])
        # Verify archive
        self.assertTrue(a.verify_archive())
        # Unpack
        a.unpack(extract_dir=self.wd)
        self.assertTrue(os.path.exists(os.path.join(
            self.wd,"example_broken_symlinks")))
        self.assertEqual(os.path.getmtime(os.path.join(
            self.wd,"example_broken_symlinks")),
                         os.path.getmtime(a.path))
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(self.wd,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in Directory(
                os.path.join(self.wd,"example_broken_symlinks")).walk():
            self.assertTrue(os.path.relpath(item,self.wd) in expected,
                            "'%s' not expected" % item)
        # Extract "working" symlink (will be broken)
        extract_dir = os.path.join(self.wd,"test_extract")
        os.mkdir(extract_dir)
        a.extract_files(name="example_broken_symlinks/subdir1/symlink1.*",
                        extract_dir=extract_dir)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,"symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,"symlink1.txt")),
                         "./ex1.txt")
        a.extract_files(name="example_broken_symlinks/subdir1/symlink1.*",
                        extract_dir=extract_dir,
                        include_path=True)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,
                         "example_broken_symlinks",
                         "subdir1",
                         "symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,
                         "example_broken_symlinks",
                         "subdir1",
                         "symlink1.txt")),
                         "./ex1.txt")
        # Extract broken symlink
        a.extract_files(
            name="example_broken_symlinks/subdir2/broken_symlink1.*",
            extract_dir=extract_dir)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,"broken_symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,"broken_symlink1.txt")),
                         "./ex3.txt")
        a.extract_files(
            name="example_broken_symlinks/subdir2/broken_symlink1.*",
            extract_dir=extract_dir,
            include_path=True)
        self.assertTrue(os.path.islink(
            os.path.join(extract_dir,
                         "example_broken_symlinks",
                         "subdir2",
                         "broken_symlink1.txt")))
        self.assertEqual(os.readlink(
            os.path.join(extract_dir,
                         "example_broken_symlinks",
                         "subdir2",
                         "broken_symlink1.txt")),
                         "./ex3.txt")

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

class TestCopyArchiveDirectory(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestCopyArchiveDirectory')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_copyarchivedirectory(self):
        """
        CopyArchiveDirectory: check properties and methods
        """
        # Build example source directory
        example_src = UnittestDir(os.path.join(self.wd, "example"))
        example_src.add("ex1.txt",type="file",content="example 1")
        example_src.add("subdir1/ex2.txt",type="file",content="example 2")
        example_src.add("subdir2/ex3.txt",type="file",content="example 3")
        example_src.add("subdir2/ex4.txt",type="symlink",target="./ex3.txt")
        example_src.create()
        # Build example copy archive dir
        os.mkdir(os.path.join(self.wd, "archive"))
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "archive",
                                                   "example"))
        example_archive.add("ex1.txt",type="file",content="example 1")
        example_archive.add("subdir1/ex2.txt",type="file",content="example 2")
        example_archive.add("subdir2/ex3.txt",type="file",content="example 3")
        example_archive.add("subdir2/ex4.txt",type="symlink",target="./ex3.txt")
        example_archive.add("ARCHIVE_README.txt", type="file")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_METADATA/checksums.md5",type="file",
                            content="""e93b3fa481be3932aa08bd68c3deee70  ex1.txt
a6b23ee7f9c084154997ea3bf5b4c1e3  subdir1/ex2.txt
d376eaa7e7aecf81dcbdd6081fae63a9  subdir2/ex3.txt
""")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "CopyArchiveDirectory",
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "replace_symlinks": "no",
  "transform_broken_symlinks": "no",
  "follow_dirlinks": "no",
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.create()
        p = example_archive.path
        # Check example loads as CopyArchiveDirectory
        c = CopyArchiveDirectory(p)
        self.assertTrue(isinstance(c, CopyArchiveDirectory))
        # Verify archive
        self.assertTrue(c.verify_archive())
        # Check against source directory
        self.assertTrue(c.verify_copy(example_src.path))

    def test_copyarchivedirectory_replaced_symlink(self):
        """
        CopyArchiveDirectory: check replaced symlink
        """
        # Build example source directory
        example_src = UnittestDir(os.path.join(self.wd, "example"))
        example_src.add("ex1.txt",type="file",content="example 1")
        example_src.add("subdir1/ex2.txt",type="file",content="example 2")
        example_src.add("subdir2/ex3.txt",type="file",content="example 3")
        example_src.add("subdir2/ex4.txt",type="symlink",target="./ex3.txt")
        example_src.create()
        # Build example copy archive dir
        os.mkdir(os.path.join(self.wd, "archive"))
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "archive",
                                                   "example"))
        example_archive.add("ex1.txt",type="file",content="example 1")
        example_archive.add("subdir1/ex2.txt",type="file",content="example 2")
        example_archive.add("subdir2/ex3.txt",type="file",content="example 3")
        example_archive.add("subdir2/ex4.txt",type="file",content="example 3")
        example_archive.add("ARCHIVE_README.txt", type="file")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_METADATA/checksums.md5",type="file",
                            content="""e93b3fa481be3932aa08bd68c3deee70  ex1.txt
a6b23ee7f9c084154997ea3bf5b4c1e3  subdir1/ex2.txt
d376eaa7e7aecf81dcbdd6081fae63a9  subdir2/ex3.txt
d376eaa7e7aecf81dcbdd6081fae63a9  subdir2/ex4.txt
""")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "CopyArchiveDirectory",
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "replace_symlinks": "yes",
  "transform_broken_symlinks": "no",
  "follow_dirlinks": "no",
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.create()
        p = example_archive.path
        # Check example loads as CopyArchiveDirectory
        c = CopyArchiveDirectory(p)
        self.assertTrue(isinstance(c, CopyArchiveDirectory))
        # Verify archive
        self.assertTrue(c.verify_archive())
        # Check against source directory
        self.assertTrue(c.verify_copy(example_src.path))

    def test_copyarchivedirectory_followed_dirlink(self):
        """
        CopyArchiveDirectory: check followed dirlink
        """
        # Build example source directory
        example_src = UnittestDir(os.path.join(self.wd, "example"))
        example_src.add("ex1.txt",type="file",content="example 1")
        example_src.add("subdir1/ex2.txt",type="file",content="example 2")
        example_src.add("subdir2/ex3.txt",type="file",content="example 3")
        example_src.add("subdir3",type="symlink",target="./subdir2")
        example_src.create()
        # Build example copy archive dir
        os.mkdir(os.path.join(self.wd, "archive"))
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "archive",
                                                   "example"))
        example_archive.add("ex1.txt",type="file",content="example 1")
        example_archive.add("subdir1/ex2.txt",type="file",content="example 2")
        example_archive.add("subdir2/ex3.txt",type="file",content="example 3")
        example_archive.add("subdir3/ex3.txt",type="file",content="example 3")
        example_archive.add("ARCHIVE_README.txt", type="file")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_METADATA/checksums.md5",type="file",
                            content="""e93b3fa481be3932aa08bd68c3deee70  ex1.txt
a6b23ee7f9c084154997ea3bf5b4c1e3  subdir1/ex2.txt
d376eaa7e7aecf81dcbdd6081fae63a9  subdir2/ex3.txt
d376eaa7e7aecf81dcbdd6081fae63a9  subdir3/ex3.txt
""")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "CopyArchiveDirectory",
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "replace_symlinks": "no",
  "transform_broken_symlinks": "no",
  "follow_dirlinks": "yes",
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.create()
        p = example_archive.path
        # Check example loads as CopyArchiveDirectory
        c = CopyArchiveDirectory(p)
        self.assertTrue(isinstance(c, CopyArchiveDirectory))
        # Verify archive
        self.assertTrue(c.verify_archive())
        # Check against source directory
        self.assertTrue(c.verify_copy(example_src.path))

    def test_copyarchivedirectory_transformed_broken_symlink(self):
        """
        CopyArchiveDirectory: check transformed broken symlink
        """
        # Build example source directory
        example_src = UnittestDir(os.path.join(self.wd, "example"))
        example_src.add("ex1.txt",type="file",content="example 1")
        example_src.add("subdir1/ex2.txt",type="file",content="example 2")
        example_src.add("subdir2/ex3.txt",type="file",content="example 3")
        example_src.add("subdir2/ex4.txt",type="symlink",target="missing.txt")
        example_src.create()
        # Build example copy archive dir
        os.mkdir(os.path.join(self.wd, "archive"))
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "archive",
                                                   "example"))
        example_archive.add("ex1.txt",type="file",content="example 1")
        example_archive.add("subdir1/ex2.txt",type="file",content="example 2")
        example_archive.add("subdir2/ex3.txt",type="file",content="example 3")
        example_archive.add("subdir2/ex4.txt",type="file",content="missing.txt")
        example_archive.add("ARCHIVE_README.txt", type="file")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_METADATA/checksums.md5",type="file",
                            content="""e93b3fa481be3932aa08bd68c3deee70  ex1.txt
a6b23ee7f9c084154997ea3bf5b4c1e3  subdir1/ex2.txt
d376eaa7e7aecf81dcbdd6081fae63a9  subdir2/ex3.txt
afb5e9e75190eea73d05fa5b0c20bd51  subdir2/ex4.txt
""")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "CopyArchiveDirectory",
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "replace_symlinks": "no",
  "transform_broken_symlinks": "yes",
  "follow_dirlinks": "no",
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.create()
        p = example_archive.path
        # Check example loads as CopyArchiveDirectory
        c = CopyArchiveDirectory(p)
        self.assertTrue(isinstance(c, CopyArchiveDirectory))
        # Verify archive
        self.assertTrue(c.verify_archive())
        # Check against source directory
        self.assertTrue(c.verify_copy(example_src.path))

    def test_copyarchivedirectory_legacy_readme(self):
        """
        CopyArchiveDirectory: check properties and methods (legacy README/no '.txt' extension)
        """
        # Build example source directory
        example_src = UnittestDir(os.path.join(self.wd, "example"))
        example_src.add("ex1.txt",type="file",content="example 1")
        example_src.add("subdir1/ex2.txt",type="file",content="example 2")
        example_src.add("subdir2/ex3.txt",type="file",content="example 3")
        example_src.add("subdir2/ex4.txt",type="symlink",target="./ex3.txt")
        example_src.create()
        # Build example copy archive dir
        os.mkdir(os.path.join(self.wd, "archive"))
        example_archive = UnittestDir(os.path.join(self.wd,
                                                   "archive",
                                                   "example"))
        example_archive.add("ex1.txt",type="file",content="example 1")
        example_archive.add("subdir1/ex2.txt",type="file",content="example 2")
        example_archive.add("subdir2/ex3.txt",type="file",content="example 3")
        example_archive.add("subdir2/ex4.txt",type="symlink",target="./ex3.txt")
        example_archive.add("ARCHIVE_README", type="file")
        example_archive.add("ARCHIVE_METADATA/manifest",type="file")
        example_archive.add("ARCHIVE_METADATA/checksums.md5",type="file",
                            content="""e93b3fa481be3932aa08bd68c3deee70  ex1.txt
a6b23ee7f9c084154997ea3bf5b4c1e3  subdir1/ex2.txt
d376eaa7e7aecf81dcbdd6081fae63a9  subdir2/ex3.txt
""")
        example_archive.add("ARCHIVE_METADATA/archiver_metadata.json",
                            type="file",
                            content="""{
  "name": "example",
  "source": "/original/path/to/example",
  "source_date": "2019-11-27 17:19:02",
  "type": "CopyArchiveDirectory",
  "user": "anon",
  "creation_date": "2023-06-16 09:58:39",
  "replace_symlinks": "no",
  "transform_broken_symlinks": "no",
  "follow_dirlinks": "no",
  "ngsarchiver_version": "0.0.1"
}
""")
        example_archive.create()
        p = example_archive.path
        # Check example loads as CopyArchiveDirectory
        c = CopyArchiveDirectory(p)
        self.assertTrue(isinstance(c, CopyArchiveDirectory))
        # Verify archive
        self.assertTrue(c.verify_archive())
        # Check against source directory
        self.assertTrue(c.verify_copy(example_src.path))


class TestReadmeFile(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestReadmeFile')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_readmefile(self):
        """
        ReadmeFile: test creating a README file
        """
        readme = ReadmeFile()
        self.assertEqual(readme.text(), "")
        readme.add("Some content")
        self.assertEqual(readme.text(), "Some content")
        readme.add("More content")
        self.assertEqual(readme.text(), "Some content\n\nMore content")
        readme_file = os.path.join(self.wd, "README")
        readme.write(readme_file)
        self.assertTrue(os.path.exists(readme_file))
        with open(readme_file, "rt") as fp:
            contents = fp.read()
            self.assertEqual(contents, "Some content\n\nMore content\n")

    def test_readmefile_wrap_lines(self):
        """
        ReadmeFile: test wrapping long lines
        """
        readme = ReadmeFile()
        self.assertEqual(readme.text(), "")
        readme.add("Some content which exceeds the 70 character width "
                   "limit and so must be wrapped onto multiple lines")
        self.assertEqual(readme.text(),
                         "Some content which exceeds the 70 character "
                         "width limit and so must be\nwrapped onto "
                         "multiple lines")

    def test_readmefile_wrap_lines_custom_width(self):
        """
        ReadmeFile: test wrapping long lines with custom width
        """
        readme = ReadmeFile(width=50)
        self.assertEqual(readme.text(), "")
        readme.add("Some content which exceeds the 50 character width "
                   "limit and so must be wrapped onto multiple lines")
        self.assertEqual(readme.text(),
                         "Some content which exceeds the 50 character "
                         "width\nlimit and so must be wrapped onto "
                         "multiple lines")

    def test_readmefile_indent_lines(self):
        """
        ReadmeFile: test indenting lines
        """
        readme = ReadmeFile()
        self.assertEqual(readme.text(), "")
        readme.add("Some content which exceeds the 70 character width "
                   "limit and so must be wrapped onto multiple lines",
                   indent="   ")
        self.assertEqual(readme.text(),
                         "   Some content which exceeds the 70 character "
                         "width limit and so must\n   be wrapped onto "
                         "multiple lines")

    def test_readmefile_no_wrapping(self):
        """
        ReadmeFile: test disabling wrapping long lines
        """
        readme = ReadmeFile()
        self.assertEqual(readme.text(), "")
        readme.add("Some content which exceeds the 70 character width "
                   "limit and will be wrapped")
        readme.add("More content also exceeding 70 characters but will not "
                   "be wrapped", wrap=False)
        readme.add("Additional long content which will again be wrapped "
                   "over multiple lines")
        self.assertEqual(readme.text(),
                         "Some content which exceeds the 70 character "
                         "width limit and will be\nwrapped\n\nMore content "
                         "also exceeding 70 characters but will not be "
                         "wrapped\n\nAdditional long content which will "
                         "again be wrapped over multiple\nlines")

    def test_readmefile_keep_newlines(self):
        """
        ReadmeFile: test preserving newlines
        """
        readme = ReadmeFile()
        self.assertEqual(readme.text(), "")
        readme.add("Content with newlines which\nwill not be preserved\n")
        readme.add("These newlines\nwill\nbe preserved", keep_newlines=True)
        readme.add("These\nwill\nnot")
        self.assertEqual(readme.text(),
                         "Content with newlines which will not be "
                         "preserved\n\nThese newlines\nwill\nbe preserved\n\n"
                         "These will not")


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

    def test_get_rundir_instance_copy_archive_directory(self):
        """
        get_rundir_instance: returns 'CopyArchiveDirectory' instance
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example.archive"))
        example_dir.add("ARCHIVE_README.txt", type="file")
        example_dir.add("ARCHIVE_METADATA/checksums.md5",type="file")
        example_dir.add("ARCHIVE_METADATA/archiver_metadata.json",type="file",
                        content="""{
  "name": "example"
}
""")
        example_dir.add("ARCHIVE_METADATA/manifest",type="file")
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir2/ex3.txt",type="file")
        example_dir.create()
        p = example_dir.path
        p = example_dir.path
        # Check correct class is returned
        d = get_rundir_instance(p)
        self.assertTrue(isinstance(d,CopyArchiveDirectory))

    def test_get_rundir_instance_copy_archive_directory_legacy_readme_no_txt_extension(self):
        """
        get_rundir_instance: returns 'CopyArchiveDirectory' instance (legacy/README without .txt)
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example.archive"))
        example_dir.add("ARCHIVE_README", type="file")
        example_dir.add("ARCHIVE_METADATA/checksums.md5",type="file")
        example_dir.add("ARCHIVE_METADATA/archiver_metadata.json",type="file",
                        content="""{
  "name": "example"
}
""")
        example_dir.add("ARCHIVE_METADATA/manifest",type="file")
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir2/ex3.txt",type="file")
        example_dir.create()
        p = example_dir.path
        p = example_dir.path
        # Check correct class is returned
        d = get_rundir_instance(p)
        self.assertTrue(isinstance(d,CopyArchiveDirectory))

    def test_get_rundir_instance_copy_archive_directory_legacy_no_readme(self):
        """
        get_rundir_instance: returns 'CopyArchiveDirectory' instance (legacy/no README)
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example.archive"))
        example_dir.add("ARCHIVE_METADATA/checksums.md5",type="file")
        example_dir.add("ARCHIVE_METADATA/archiver_metadata.json",type="file",
                        content="""{
  "name": "example"
}
""")
        example_dir.add("ARCHIVE_METADATA/manifest",type="file")
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir2/ex3.txt",type="file")
        example_dir.create()
        p = example_dir.path
        p = example_dir.path
        # Check correct class is returned
        d = get_rundir_instance(p)
        self.assertTrue(isinstance(d,CopyArchiveDirectory))

    def test_get_rundir_instance_archive_directory(self):
        """
        get_rundir_instance: returns 'ArchiveDirectory' instance
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example.archive"))
        example_dir.add("ARCHIVE_METADATA/archive_checksums.md5",type="file")
        example_dir.add("ARCHIVE_METADATA/archiver_metadata.json",type="file",
                        content="""{
  "name": "example",
  "compression_level": 6
}
""")
        example_dir.add("ARCHIVE_METADATA/manifest.txt",type="file")
        example_dir.add("ARCHIVE_README.txt",type="file")
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

    def test_get_rundir_instance_archive_directory_readme_no_txt_extension(self):
        """
        get_rundir_instance: returns 'ArchiveDirectory' instance (README without .txt extension)
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example.archive"))
        example_dir.add("ARCHIVE_METADATA/archive_checksums.md5",type="file")
        example_dir.add("ARCHIVE_METADATA/archiver_metadata.json",type="file",
                        content="""{
  "name": "example",
  "compression_level": 6
}
""")
        example_dir.add("ARCHIVE_METADATA/manifest.txt",type="file")
        example_dir.add("ARCHIVE_README",type="file")
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

    def test_get_rundir_instance_archive_directory_no_readme(self):
        """
        get_rundir_instance: returns 'ArchiveDirectory' instance (no README)
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example.archive"))
        example_dir.add("ARCHIVE_METADATA/archive_checksums.md5",type="file")
        example_dir.add("ARCHIVE_METADATA/archiver_metadata.json",type="file",
                        content="""{
  "name": "example",
  "compression_level": 6
}
""")
        example_dir.add("ARCHIVE_METADATA/manifest.txt",type="file")
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

    def test_get_rundir_instance_legacy_archive_directory(self):
        """
        get_rundir_instance: returns 'ArchiveDirectory' instance (legacy archive)
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example.archive"))
        example_dir.add(".ngsarchiver/archive.md5",type="file")
        example_dir.add(".ngsarchiver/archive_metadata.json",type="file",
                        content="""{
  "name": "example",
  "compression_level": 6
}
""")
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
        self.assertEqual(a.archive_metadata["type"], "ArchiveDirectory")
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        for item in ("example.tar.gz",
                     "example.md5",
                     "ARCHIVE_README.txt",
                     "ARCHIVE_TREE.txt",
                     "ARCHIVE_FILELIST.txt",
                     "ARCHIVE_METADATA",
                     "ARCHIVE_METADATA/archive_checksums.md5",
                     "ARCHIVE_METADATA/archiver_metadata.json",
                     "ARCHIVE_METADATA/manifest",):
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check MD5 files are properly formatted
        for md5file in ("example.md5",
                        "ARCHIVE_METADATA/archive_checksums.md5"):
            with open(os.path.join(archive_dir, md5file), "rt") as fp:
                for line in fp:
                    line = line.rstrip("\n")
                    self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                    is not None,
                                    f"{md5file}: incorrectly formatted "
                                    f"MD5 checksum line: {line}")
        # Check file list
        with open(os.path.join(archive_dir, "ARCHIVE_FILELIST.txt"), "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                if " -> " not in line:
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, line)),
                                    f"{line}: in filelist but doesn't exist")
                    if line.endswith(os.sep):
                        self.assertTrue(os.path.isdir(
                            os.path.join(d.path, line)),
                                        f"{line}: is not a directory")
                    else:
                        self.assertFalse(os.path.islink(
                            os.path.join(d.path, line)),
                                        f"{line}: is a link")
                else:
                    f,l = line.split(" -> ")
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, f)),
                                    f"{f}: in filelist but doesn't exist")
                    self.assertEqual(os.readlink(os.path.join(d.path, f)), l,
                                     f"{f}: incorrect target in filelist ({l})")

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
        self.assertEqual(a.archive_metadata["type"], "ArchiveDirectory")
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        for item in ("subdir1.tar.gz",
                     "subdir1.md5",
                     "subdir2.tar.gz",
                     "subdir2.md5",
                     "ARCHIVE_README.txt",
                     "ARCHIVE_TREE.txt",
                     "ARCHIVE_FILELIST.txt",
                     "ARCHIVE_METADATA",
                     "ARCHIVE_METADATA/archive_checksums.md5",
                     "ARCHIVE_METADATA/archiver_metadata.json",
                     "ARCHIVE_METADATA/manifest",):
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check MD5 files are properly formatted
        for md5file in ("subdir1.md5",
                        "subdir2.md5",
                        "ARCHIVE_METADATA/archive_checksums.md5"):
            with open(os.path.join(archive_dir, md5file), "rt") as fp:
                for line in fp:
                    line = line.rstrip("\n")
                    self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                    is not None,
                                    f"{md5file}: incorrectly formatted "
                                    f"MD5 checksum line: {line}")
        # Check file list
        with open(os.path.join(archive_dir, "ARCHIVE_FILELIST.txt"), "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                if " -> " not in line:
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, line)),
                                    f"{line}: in filelist but doesn't exist")
                    if line.endswith(os.sep):
                        self.assertTrue(os.path.isdir(
                            os.path.join(d.path, line)),
                                        f"{line}: is not a directory")
                    else:
                        self.assertFalse(os.path.islink(
                            os.path.join(d.path, line)),
                                        f"{line}: is a link")
                else:
                    f,l = line.split(" -> ")
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, f)),
                                    f"{f}: in filelist but doesn't exist")
                    self.assertEqual(os.readlink(os.path.join(d.path, f)), l,
                                     f"{f}: incorrect target in filelist ({l})")

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
        self.assertEqual(a.archive_metadata["type"], "ArchiveDirectory")
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
                     "ARCHIVE_README.txt",
                     "ARCHIVE_TREE.txt",
                     "ARCHIVE_FILELIST.txt",
                     "ARCHIVE_METADATA",
                     "ARCHIVE_METADATA/archive_checksums.md5",
                     "ARCHIVE_METADATA/archiver_metadata.json",
                     "ARCHIVE_METADATA/manifest",):
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check MD5 files are properly formatted
        for md5file in ("subdir1.md5",
                        "subdir2.md5",
                        "miscellaneous.md5",
                        "ARCHIVE_METADATA/archive_checksums.md5"):
            with open(os.path.join(archive_dir, md5file), "rt") as fp:
                for line in fp:
                    line = line.rstrip("\n")
                    self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                    is not None,
                                    f"{md5file}: incorrectly formatted "
                                    f"MD5 checksum line: {line}")
        # Check file list
        with open(os.path.join(archive_dir, "ARCHIVE_FILELIST.txt"), "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                if " -> " not in line:
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, line)),
                                    f"{line}: in filelist but doesn't exist")
                    if line.endswith(os.sep):
                        self.assertTrue(os.path.isdir(
                            os.path.join(d.path, line)),
                                        f"{line}: is not a directory")
                    else:
                        self.assertFalse(os.path.islink(
                            os.path.join(d.path, line)),
                                        f"{line}: is a link")
                else:
                    f,l = line.split(" -> ")
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, f)),
                                    f"{f}: in filelist but doesn't exist")
                    self.assertEqual(os.readlink(os.path.join(d.path, f)), l,
                                     f"{f}: incorrect target in filelist ({l})")

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
        self.assertEqual(a.archive_metadata["type"], "ArchiveDirectory")
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
                     "ARCHIVE_README.txt",
                     "ARCHIVE_TREE.txt",
                     "ARCHIVE_FILELIST.txt",
                     "ARCHIVE_METADATA",
                     "ARCHIVE_METADATA/archive_checksums.md5",
                     "ARCHIVE_METADATA/archiver_metadata.json",
                     "ARCHIVE_METADATA/manifest",):
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check MD5 files are properly formatted
        for md5file in ("subdir1.md5",
                        "subdir2.md5",
                        "miscellaneous.md5",
                        "ARCHIVE_METADATA/archive_checksums.md5"):
            with open(os.path.join(archive_dir, md5file), "rt") as fp:
                for line in fp:
                    line = line.rstrip("\n")
                    self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                    is not None,
                                    f"{md5file}: incorrectly formatted "
                                    f"MD5 checksum line: {line}")
        # Check file list
        with open(os.path.join(archive_dir, "ARCHIVE_FILELIST.txt"), "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                if " -> " not in line:
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, line)),
                                    f"{line}: in filelist but doesn't exist")
                    if line.endswith(os.sep):
                        self.assertTrue(os.path.isdir(
                            os.path.join(d.path, line)),
                                        f"{line}: is not a directory")
                    else:
                        self.assertFalse(os.path.islink(
                            os.path.join(d.path, line)),
                                        f"{line}: is a link")
                else:
                    f,l = line.split(" -> ")
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, f)),
                                    f"{f}: in filelist but doesn't exist")
                    self.assertEqual(os.readlink(os.path.join(d.path, f)), l,
                                     f"{f}: incorrect target in filelist ({l})")

    def test_make_archive_dir_multi_volume_single_archive(self):
        """
        make_archive_dir: single multi-volume archive
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        for ix in range(0,20):
            example_dir.add("ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,out_dir=self.wd,volume_size='12K')
        self.assertTrue(isinstance(a,ArchiveDirectory))
        self.assertEqual(a.archive_metadata["type"], "ArchiveDirectory")
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        expected = ("example.00.tar.gz",
                    "example.01.tar.gz",
                    "example.00.md5",
                    "example.01.md5",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_TREE.txt",
                    "ARCHIVE_FILELIST.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/archive_checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json",
                    "ARCHIVE_METADATA/manifest",)
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in a.walk():
            self.assertTrue(os.path.relpath(item,archive_dir) in expected,
                            "'%s' not expected" % item)
        # Check MD5 files are properly formatted
        for md5file in ("example.00.md5",
                        "example.01.md5",
                        "ARCHIVE_METADATA/archive_checksums.md5"):
            with open(os.path.join(archive_dir, md5file), "rt") as fp:
                for line in fp:
                    line = line.rstrip("\n")
                    self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                    is not None,
                                    f"{md5file}: incorrectly formatted "
                                    f"MD5 checksum line: {line}")
        # Check file list
        with open(os.path.join(archive_dir, "ARCHIVE_FILELIST.txt"), "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                if " -> " not in line:
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, line)),
                                    f"{line}: in filelist but doesn't exist")
                    if line.endswith(os.sep):
                        self.assertTrue(os.path.isdir(
                            os.path.join(d.path, line)),
                                        f"{line}: is not a directory")
                    else:
                        self.assertFalse(os.path.islink(
                            os.path.join(d.path, line)),
                                        f"{line}: is a link")
                else:
                    f,l = line.split(" -> ")
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, f)),
                                    f"{f}: in filelist but doesn't exist")
                    self.assertEqual(os.readlink(os.path.join(d.path, f)), l,
                                     f"{f}: incorrect target in filelist ({l})")

    def test_make_archive_dir_multi_volume_multiple_subarchives(self):
        """
        make_archive_dir: multiple multi-volume subarchives
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        for ix in range(0,40):
            example_dir.add("subdir1/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir2/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,sub_dirs=('subdir1','subdir2'),
                             out_dir=self.wd,volume_size='12K')
        self.assertTrue(isinstance(a,ArchiveDirectory))
        self.assertEqual(a.archive_metadata["type"], "ArchiveDirectory")
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
                    "ARCHIVE_README.txt",
                    "ARCHIVE_TREE.txt",
                    "ARCHIVE_FILELIST.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/archive_checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json",
                    "ARCHIVE_METADATA/manifest",)
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in a.walk():
            self.assertTrue(os.path.relpath(item,archive_dir) in expected,
                            "'%s' not expected" % item)
        # Check MD5 files are properly formatted
        for md5file in ("subdir1.00.md5",
                        "subdir1.01.md5",
                        "subdir2.00.md5",
                        "subdir2.01.md5",
                        "ARCHIVE_METADATA/archive_checksums.md5"):
            with open(os.path.join(archive_dir, md5file), "rt") as fp:
                for line in fp:
                    line = line.rstrip("\n")
                    self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                    is not None,
                                    f"{md5file}: incorrectly formatted "
                                    f"MD5 checksum line: {line}")
        # Check file list
        with open(os.path.join(archive_dir, "ARCHIVE_FILELIST.txt"), "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                if " -> " not in line:
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, line)),
                                    f"{line}: in filelist but doesn't exist")
                    if line.endswith(os.sep):
                        self.assertTrue(os.path.isdir(
                            os.path.join(d.path, line)),
                                        f"{line}: is not a directory")
                    else:
                        self.assertFalse(os.path.islink(
                            os.path.join(d.path, line)),
                                        f"{line}: is a link")
                else:
                    f,l = line.split(" -> ")
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, f)),
                                    f"{f}: in filelist but doesn't exist")
                    self.assertEqual(os.readlink(os.path.join(d.path, f)), l,
                                     f"{f}: incorrect target in filelist ({l})")

    def test_make_archive_dir_multi_volume_multiple_subarchives_including_misc(self):
        """
        make_archive_dir: multiple multi-volume subarchives (including miscellaneous)
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        for ix in range(0,40):
            example_dir.add("subdir1/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir2/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir3/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
        example_dir.add("ex4.txt",type="file",content="Some text\n")
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,sub_dirs=('subdir1','subdir2'),
                             misc_objects=('ex4.txt','subdir3'),
                             out_dir=self.wd,
                             volume_size='12K')
        self.assertTrue(isinstance(a,ArchiveDirectory))
        self.assertEqual(a.archive_metadata["type"], "ArchiveDirectory")
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
                    "miscellaneous.00.md5",
                    "miscellaneous.01.md5",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_TREE.txt",
                    "ARCHIVE_FILELIST.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/archive_checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json",
                    "ARCHIVE_METADATA/manifest",)
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in a.walk():
            self.assertTrue(os.path.relpath(item,archive_dir) in expected,
                            "'%s' not expected" % item)
        # Check MD5 files are properly formatted
        for md5file in ("subdir1.00.md5",
                        "subdir1.01.md5",
                        "subdir2.00.md5",
                        "subdir2.01.md5",
                        "miscellaneous.00.md5",
                        "miscellaneous.01.md5",
                        "ARCHIVE_METADATA/archive_checksums.md5"):
            with open(os.path.join(archive_dir, md5file), "rt") as fp:
                for line in fp:
                    line = line.rstrip("\n")
                    self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                    is not None,
                                    f"{md5file}: incorrectly formatted "
                                    f"MD5 checksum line: {line}")
        # Check file list
        with open(os.path.join(archive_dir, "ARCHIVE_FILELIST.txt"), "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                if " -> " not in line:
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, line)),
                                    f"{line}: in filelist but doesn't exist")
                    if line.endswith(os.sep):
                        self.assertTrue(os.path.isdir(
                            os.path.join(d.path, line)),
                                        f"{line}: is not a directory")
                    else:
                        self.assertFalse(os.path.islink(
                            os.path.join(d.path, line)),
                                        f"{line}: is a link")
                else:
                    f,l = line.split(" -> ")
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, f)),
                                    f"{f}: in filelist but doesn't exist")
                    self.assertEqual(os.readlink(os.path.join(d.path, f)), l,
                                     f"{f}: incorrect target in filelist ({l})")

    def test_make_archive_dir_multi_volume_multiple_subarchives_including_misc_and_extra_files(self):
        """
        make_archive_dir: multiple multi-volume subarchives (including miscellaneous and extra files)
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        for ix in range(0,40):
            example_dir.add("subdir1/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir2/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir3/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
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
                             volume_size='12K')
        self.assertTrue(isinstance(a,ArchiveDirectory))
        self.assertEqual(a.archive_metadata["type"], "ArchiveDirectory")
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
                    "miscellaneous.00.md5",
                    "miscellaneous.01.md5",
                    "ex5.txt",
                    "ex6.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_TREE.txt",
                    "ARCHIVE_FILELIST.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/archive_checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json",
                    "ARCHIVE_METADATA/manifest",)
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in a.walk():
            self.assertTrue(os.path.relpath(item,archive_dir) in expected,
                            "'%s' not expected" % item)
        # Check MD5 files are properly formatted
        for md5file in ("subdir1.00.md5",
                        "subdir1.01.md5",
                        "subdir2.00.md5",
                        "subdir2.01.md5",
                        "miscellaneous.00.md5",
                        "miscellaneous.01.md5",
                        "ARCHIVE_METADATA/archive_checksums.md5"):
            with open(os.path.join(archive_dir, md5file), "rt") as fp:
                for line in fp:
                    line = line.rstrip("\n")
                    self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                    is not None,
                                    f"{md5file}: incorrectly formatted "
                                    f"MD5 checksum line: {line}")
        # Check file list
        with open(os.path.join(archive_dir, "ARCHIVE_FILELIST.txt"), "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                if " -> " not in line:
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, line)),
                                    f"{line}: in filelist but doesn't exist")
                    if line.endswith(os.sep):
                        self.assertTrue(os.path.isdir(
                            os.path.join(d.path, line)),
                                        f"{line}: is not a directory")
                    else:
                        self.assertFalse(os.path.islink(
                            os.path.join(d.path, line)),
                                        f"{line}: is a link")
                else:
                    f,l = line.split(" -> ")
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, f)),
                                    f"{f}: in filelist but doesn't exist")
                    self.assertEqual(os.readlink(os.path.join(d.path, f)), l,
                                     f"{f}: incorrect target in filelist ({l})")

    def test_make_archive_dir_handle_symlinks(self):
        """
        make_archive_dir: handle symlinks
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/symlink1.txt",type="symlink",target="./ex2.txt")
        example_dir.create()
        p = example_dir.path
        # Make archive directory
        d = Directory(p)
        a = make_archive_dir(d,out_dir=self.wd)
        self.assertTrue(isinstance(a,ArchiveDirectory))
        self.assertEqual(a.archive_metadata["type"], "ArchiveDirectory")
        # Check resulting archive
        archive_dir = os.path.join(self.wd,"example.archive")
        self.assertEqual(a.path,archive_dir)
        self.assertTrue(os.path.exists(archive_dir))
        expected = ("example.tar.gz",
                    "example.md5",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_TREE.txt",
                    "ARCHIVE_FILELIST.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/archive_checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(archive_dir,item)),
                "missing '%s'" % item)
        # Check extra items aren't present
        for item in a.walk():
            self.assertTrue(os.path.relpath(item,archive_dir) in expected,
                            "'%s' not expected" % item)
        # Check contents of 'symlinks' metadata file
        with open(os.path.join(archive_dir,
                               "ARCHIVE_METADATA",
                               "symlinks"),'rt') as fp:
            self.assertEqual(fp.read(),
                             "example/subdir/symlink1.txt\texample.tar.gz\n")
        # Check MD5 files are properly formatted
        for md5file in ("example.md5",
                        "ARCHIVE_METADATA/archive_checksums.md5"):
            with open(os.path.join(archive_dir, md5file), "rt") as fp:
                for line in fp:
                    line = line.rstrip("\n")
                    self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                    is not None,
                                    f"{md5file}: incorrectly formatted "
                                    f"MD5 checksum line: {line}")
        # Check file list
        with open(os.path.join(archive_dir, "ARCHIVE_FILELIST.txt"), "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                if " -> " not in line:
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, line)),
                                    f"{line}: in filelist but doesn't exist")
                    if line.endswith(os.sep):
                        self.assertTrue(os.path.isdir(
                            os.path.join(d.path, line)),
                                        f"{line}: is not a directory")
                    else:
                        self.assertFalse(os.path.islink(
                            os.path.join(d.path, line)),
                                        f"{line}: is a link")
                else:
                    f,l = line.split(" -> ")
                    self.assertTrue(os.path.lexists(
                        os.path.join(d.path, f)),
                                    f"{f}: in filelist but doesn't exist")
                    self.assertEqual(os.readlink(os.path.join(d.path, f)), l,
                                     f"{f}: incorrect target in filelist ({l})")

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

    def test_make_archive_tgz_with_include_files(self):
        """
        make_archive_tgz: specify list of included files
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
                                          include_files=included_files),
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

    def test_make_archive_tgz_with_exclude_files(self):
        """
        make_archive_tgz: specify list of excluded files
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text")
        example_dir.add("exclude1.txt",type="file")
        example_dir.add("subdir/ex2.txt",type="file",content="More text")
        example_dir.add("subdir/exclude2.txt",type="file")
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_path = "%s.tar.gz" % test_archive
        excluded_files = [os.path.join(p,f)
                          for f in ("exclude1.txt",
                                    "subdir/exclude2.txt")]
        self.assertEqual(make_archive_tgz(test_archive,p,
                                          exclude_files=excluded_files),
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
        for ix in range(0,20):
            example_dir.add("ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_paths = ["%s.%02d.tar.gz" % (test_archive,ix)
                              for ix in range(0,2)]
        self.assertEqual(make_archive_multitgz(test_archive,p,size='12K'),
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
        for ix in range(0,20):
            example_dir.add("ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_paths = ["%s.%02d.tar.gz" % (test_archive,ix)
                              for ix in range(0,2)]
        self.assertEqual(make_archive_multitgz(test_archive,p,
                                               base_dir="example",
                                               size='12K'),
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

    def test_make_archive_multitgz_with_include_files(self):
        """
        make_archive_multitgz: archive with list of included files
        """
        # Build example dir
        #text = random_text(5000)
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        for ix in range(0,20):
            example_dir.add("ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
        example_dir.create()
        p = example_dir.path
        # Overlay example dir with a subset of files
        # Only needed to generate a list of files
        overlay_dir = UnittestDir(os.path.join(self.wd,"example"))
        for ix in range(0,20,2):
            overlay_dir.add("ex%d.txt" % ix,type="file")
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_paths = ["%s.%02d.tar.gz" % (test_archive,ix)
                              for ix in range(0,1)]
        included_files = overlay_dir.list(prefix=p)
        self.assertEqual(make_archive_multitgz(test_archive,p,
                                               size='12K',
                                               include_files=included_files),
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

    def test_make_archive_multitgz_with_exclude_files(self):
        """
        make_archive_multitgz: archive with list of excluded files
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        for ix in range(0,20):
            example_dir.add("ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
        example_dir.create()
        p = example_dir.path
        # Overlay example dir with a subset of files
        # Only needed to generate a list of files
        overlay_dir = UnittestDir(os.path.join(self.wd,"example"))
        for ix in range(0,20,2):
            overlay_dir.add("ex%d.txt" % ix,type="file")
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_paths = ["%s.%02d.tar.gz" % (test_archive,ix)
                              for ix in range(0,2)]
        excluded_files = overlay_dir.list(prefix=p)
        self.assertEqual(make_archive_multitgz(test_archive,p,
                                               size='12K',
                                               exclude_files=excluded_files),
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
                    self.assertFalse(f in expected)
                    members.add(f)
        # Check no expected members are present in the archive
        for f in expected:
            self.assertFalse(f in members)

    def test_make_archive_multitgz_non_default_compression_level(self):
        """
        make_archive_multitgz: archive setting volume size and compression level
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        for ix in range(0,20):
            example_dir.add("ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
            example_dir.add("subdir/ex%d.txt" % ix,
                            type="file",
                            content=random_text(1000))
        example_dir.create()
        p = example_dir.path
        # Make archive
        test_archive = os.path.join(self.wd,"test_archive")
        test_archive_paths = ["%s.%02d.tar.gz" % (test_archive,ix)
                              for ix in range(0,2)]
        self.assertEqual(make_archive_multitgz(test_archive,p,
                                               size='12K',
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

class TestMakeCopy(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMakeArchiveDir')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_make_copy(self):
        """
        make_copy: no symlinks
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        p = example_dir.path
        # Location for copy
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d, dest_dir)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting copy
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt":
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                self.assertEqual(len(line.rstrip("\n").split("  ")), 2,
                                 f"checksum file: incorrectly formatted "
                                 f"line: {line.rstrip()}")

    def test_make_copy_handle_hidden(self):
        """
        make_copy: handle hidden files and directories
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/.ex3.txt", type="file", content="Hidden!\n")
        example_dir.add(".subdir/ex4.txt", type="file", content="Hidden!\n")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d,dest_dir)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/.ex3.txt",
                    ".subdir",
                    ".subdir/ex4.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt":
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_handle_symlink(self):
        """
        make_copy: handle symlink
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/symlink1.txt",type="symlink",target="./ex2.txt")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d,dest_dir)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/symlink1.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt":
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check symlink is still a symlink
        self.assertTrue(os.path.islink(os.path.join(dest_dir,
                                                    "subdir",
                                                    "symlink1.txt")))
        # Check symlink appears in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/symlink1.txt",):
                self.assertTrue(f in symlinks, "%s: not in symlinks file" % f)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_handle_external_symlink(self):
        """
        make_copy: handle external symlink
        """
        # Build example directory
        with open(os.path.join(self.wd, "external.txt"), "wt") as fp:
            fp.write("External file\n")
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/rel_ext_symlink.txt",type="symlink",
                        target="../../external.txt")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d,dest_dir)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/rel_ext_symlink.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt" and \
               "symlink" not in item:
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check symlink is still a symlink
        self.assertTrue(os.path.islink(os.path.join(dest_dir,
                                                    "subdir",
                                                    "rel_ext_symlink.txt")))
        # Check symlink appears in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/rel_ext_symlink.txt",):
                self.assertTrue(f in symlinks, "%s: not in symlinks file" % f)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_handle_broken_symlink(self):
        """
        make_copy: handle broken symlink
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/broken_symlink.txt",type="symlink",
                        target="doesnt_exist.txt")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d,dest_dir)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/broken_symlink.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/broken_symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt" and \
               "symlink" not in item:
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check symlink is still a symlink
        self.assertTrue(os.path.islink(os.path.join(dest_dir,
                                                    "subdir",
                                                    "broken_symlink.txt")))
        # Check symlink appears in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/broken_symlink.txt",):
                self.assertTrue(f in symlinks, "%s: not in symlinks file" % f)
        # Check symlink appears in broken symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "broken_symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/broken_symlink.txt",):
                self.assertTrue(f in symlinks,
                                "%s: not in broken_symlinks file" % f)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_handle_hard_link(self):
        """
        make_copy: handle hard link
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/link1.txt",type="link",
                        target=os.path.join(self.wd,
                                            "example",
                                            "subdir",
                                            "ex2.txt"))
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d,dest_dir)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/link1.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt":
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check hard linked file has been replaced
        link = os.path.join(dest_dir, "subdir", "link1.txt")
        self.assertFalse(
            os.path.isfile(link) and os.stat(link).st_nlink > 1)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_replace_symlink(self):
        """
        make_copy: replace internal symlink
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/ex3.txt",type="symlink",target="./ex2.txt")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d, dest_dir, replace_symlinks=True)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/ex3.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt":
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check replaced file is not a symlink
        self.assertFalse(os.path.islink(os.path.join(dest_dir,
                                                     "subdir",
                                                     "ex3.txt")))
        # Check replaced file appears in checksum file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            self.assertTrue("subdir/ex3.txt" in fp.read())
        # Check symlink appears in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/ex3.txt",):
                self.assertTrue(f in symlinks, "%s: not in symlinks file" % f)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_replace_external_symlink(self):
        """
        make_copy: replace external symlink
        """
        # Build example directory
        with open(os.path.join(self.wd, "external.txt"), "wt") as fp:
            fp.write("External file\n")
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/rel_ext_symlink.txt",type="symlink",
                        target="../../external.txt")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d,dest_dir,replace_symlinks=True)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/rel_ext_symlink.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt" and \
               "symlink" not in item:
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check replaced file is not a symlink
        self.assertFalse(os.path.islink(os.path.join(dest_dir,
                                                     "subdir",
                                                     "rel_ext_symlink.txt")))
        # Check replaced file appears in checksum file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            self.assertTrue("subdir/rel_ext_symlink.txt" in fp.read())
        # Check symlink appears in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/rel_ext_symlink.txt",):
                self.assertTrue(f in symlinks, "%s: not in symlinks file" % f)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_transform_unresolvable_symlink(self):
        """
        make_copy: transform unresolvable symlink (symlink loop)
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/symlink_to_self",
                        type="symlink",
                        target=os.path.join(self.wd,
                                            "example",
                                            "subdir",
                                            "symlink_to_self"))
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d, dest_dir, transform_broken_symlinks=True)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/symlink_to_self",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/unresolvable_symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt" and \
               not os.path.basename(item) == "symlink_to_self":
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check replaced file is not a symlink
        self.assertFalse(os.path.islink(os.path.join(dest_dir,
                                                     "subdir",
                                                     "symlink_to_self")))
        # Check replaced file appears in checksum file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            self.assertTrue("subdir/symlink_to_self" in fp.read())
        # Check symlink appears in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/symlink_to_self",):
                self.assertTrue(f in symlinks, "%s: not in symlinks file" % f)
        # Check symlink appears in unresolvable symlinks file
        with open(os.path.join(dest_dir,
                               "ARCHIVE_METADATA",
                               "unresolvable_symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/symlink_to_self",):
                self.assertTrue(f in symlinks,
                                "%s: not in unresolvable symlinks file" % f)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_replace_broken_symlink(self):
        """
        make_copy: fails attempting to replace broken symlink
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/broken_symlink.txt",type="symlink",
                        target="doesnt_exist.txt")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        self.assertRaises(NgsArchiverException,
                          make_copy,
                          d,
                          dest_dir,
                          replace_symlinks=True)

    def test_make_copy_transform_broken_symlink(self):
        """
        make_copy: transform broken symlink into placeholder
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/broken_symlink.txt",type="symlink",
                        target="doesnt_exist.txt")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d,
                       dest_dir,
                       transform_broken_symlinks=True)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/broken_symlink.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/broken_symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt" and \
               "symlink" not in item:
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check broken symlink was transformed into file
        self.assertFalse(os.path.islink(
            os.path.join(dest_dir, "subdir", "broken_symlink.txt")))
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check placeholder file appears in checksum file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            self.assertTrue("subdir/broken_symlink.txt" in fp.read())
        # Check symlink appears in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/broken_symlink.txt",):
                self.assertTrue(f in symlinks, "%s: not in symlinks file" % f)
        # Check symlink appears in broken symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "broken_symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/broken_symlink.txt",):
                self.assertTrue(f in symlinks,
                                "%s: not in broken_symlinks file" % f)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_replace_and_transform_symlinks(self):
        """
        make_copy: replace working symlinks & transform broken links
        """
        # Build example directory with internal, external and broken links
        with open(os.path.join(self.wd, "external.txt"), "wt") as fp:
            fp.write("External file\n")
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("symlink1.txt",type="symlink",target="./ex1.txt")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/rel_ext_symlink.txt",type="symlink",
                        target="../../external.txt")
        example_dir.add("subdir/broken_symlink.txt",type="symlink",
                        target="doesnt_exist.txt")
        example_dir.create()
        p = example_dir.path
        # Make straight copy
        d = Directory(p)
        dest_dir = os.path.join(self.wd, "copies", "example1")
        dd = make_copy(d, dest_dir, replace_symlinks=True,
                       transform_broken_symlinks=True)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "symlink1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/rel_ext_symlink.txt",
                    "subdir/broken_symlink.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/broken_symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt" and \
               "symlink" not in item:
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check replaced file is not a symlink
        self.assertFalse(os.path.islink(os.path.join(dest_dir,
                                                     "symlink1.txt")))
        # Check broken symlink was transformed into file
        self.assertFalse(os.path.islink(
            os.path.join(dest_dir, "subdir", "broken_symlink.txt")))
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check symlink appears in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("symlink1.txt",
                      "subdir/rel_ext_symlink.txt",
                      "subdir/broken_symlink.txt"):
                self.assertTrue(f in symlinks, "%s: not in symlinks file" % f)
        # Check symlink appears in broken symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "broken_symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/broken_symlink.txt",):
                self.assertTrue(f in symlinks,
                                "%s: not in broken_symlinks file" % f)
        # Make copy replacing symlinks and transforming broken links
        d = Directory(p)
        dest_dir = os.path.join(self.wd, "copies", "example2")
        dd = make_copy(d, dest_dir, replace_symlinks=True,
                       transform_broken_symlinks=True)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "symlink1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/rel_ext_symlink.txt",
                    "subdir/broken_symlink.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/broken_symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.lexists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt" and \
               "symlink" not in item:
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check broken symlink was transformed into file
        self.assertFalse(os.path.islink(
            os.path.join(dest_dir, "subdir", "broken_symlink.txt")))
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check replaced and placeholder files appears in checksums
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            chksums = fp.read()
            for f in ("symlink1.txt",
                      "subdir/rel_ext_symlink.txt",
                      "subdir/broken_symlink.txt"):
                self.assertTrue(f in chksums, "%s: not in checksum file" % f)
        # Check symlink appears in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("symlink1.txt",
                      "subdir/rel_ext_symlink.txt",
                      "subdir/broken_symlink.txt"):
                self.assertTrue(f in symlinks, "%s: not in symlinks file" % f)
        # Check symlink appears in broken symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "broken_symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("subdir/broken_symlink.txt",):
                self.assertTrue(f in symlinks,
                                "%s: not in broken_symlinks file" % f)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_replace_and_transform_symlink_pointing_to_broken_link(self):
        """
        make_copy: replace/transform links with symlink that points to a broken link
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/broken_link", type="symlink",
                        target="doesnt_exist")
        example_dir.add("subdir/symlink_to_broken", type="symlink",
                        target="./broken_link")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d, dest_dir, replace_symlinks=True,
                       transform_broken_symlinks=True)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir",
                    "subdir/ex2.txt",
                    "subdir/broken_link",
                    "subdir/symlink_to_broken",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/broken_symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt" and \
               os.path.basename(item) not in ("broken_link",
                                              "symlink_to_broken"):
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            self.assertTrue(os.path.relpath(item, dest_dir) in expected,
                            "'%s' not expected" % item)
        # Check replaced/transformed files exist and are not symlinks
        for f in ("broken_link", "symlink_to_broken"):
            self.assertTrue(os.path.exists(os.path.join(dest_dir, "subdir", f)),
                            f"{f}: doesn't exist (but should)")
            self.assertFalse(os.path.islink(os.path.join(dest_dir, "subdir", f)),
                             f"{f}: is a symlink (but shouldn't be)")
        # Check replaced/transformed files appear in checksum file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            checksum_files = [line.split("  ")[-1] for line in fp.read().split("\n")]
            for f in ("broken_link", "symlink_to_broken"):
                self.assertTrue(f"subdir/{f}" in checksum_files,
                                "%s: not in checksums file" % f)
        # Check replaced/transformed symlinks appear in symlinks file
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "symlinks"),
                  "rt") as fp:
            symlinks = [line.split("\t")[0] for line in fp.read().split("\n")]
            for f in ("broken_link", "symlink_to_broken",):
                self.assertTrue(f"subdir/{f}" in symlinks,
                                "%s: not in symlinks file" % f)
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_follow_dirlink(self):
        """
        make_copy: follow symlink to directory (dirlink)
        """
        # Build example directories
        external_dir = UnittestDir(os.path.join(self.wd, "external_dir"))
        external_dir.add("ex4.txt", type="file", content="External file\n")
        external_dir.add("ex5.txt", type="symlink", target="./ex4.txt")
        external_dir.add("subdir2/ex6.txt", type="file",
                         content="Another external file\n")
        external_dir.create()
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt", type="file", content="Example text\n")
        example_dir.add("subdir/ex2.txt", type="file", content="More text\n")
        example_dir.add("subdir/ex3.txt", type="symlink", target="./ex2.txt")
        example_dir.add("subdir/external_dir", type="symlink",
                        target="../../external_dir")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d, dest_dir, follow_dirlinks=True)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir/",
                    "subdir/ex2.txt",
                    "subdir/ex3.txt",
                    "subdir/external_dir/",
                    "subdir/external_dir/ex4.txt",
                    "subdir/external_dir/ex5.txt",
                    "subdir/external_dir/subdir2/",
                    "subdir/external_dir/subdir2/ex6.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA/",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt":
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            rel_path = os.path.relpath(item, dest_dir)
            if os.path.isdir(item):
                rel_path = rel_path + "/"
            self.assertTrue(rel_path in expected, "'%s' not expected" % item)
        # Check that dirlink was transformed to an actual directory
        self.assertFalse(
            os.path.islink(os.path.join(dest_dir, "subdir", "external_dir")),
            "dirlink is still a symlink")
        # Check symlinks to files are still links
        for f in ("subdir/ex3.txt",
                  "subdir/external_dir/ex5.txt",):
            self.assertTrue(os.path.islink(os.path.join(dest_dir, f)),
                            f"{f} is not a symlink (but should be)")
        # Check the manifest contains all the files
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "manifest"),
                  "rt") as fp:
            manifest_file_list = []
            for line in fp:
                manifest_file_list.append(line.rstrip().split("\t")[-1])
            for item in [x for x in expected
                         if not x.startswith("ARCHIVE_METADATA") and
                         x != "ARCHIVE_README.txt"]:
                self.assertTrue(item in manifest_file_list,
                                f"{item}: not in manifest")
        # Check that checksum file contains all the (non-symlink) files
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            checksum_file_list = []
            for line in fp:
                checksum_file_list.append(line.rstrip().split("  ")[-1])
            for item in [x for x in expected
                         if not x.startswith("ARCHIVE_METADATA/") and
                         x != "ARCHIVE_README.txt" and
                         os.path.basename(x) not in ("ex3.txt", "ex5.txt")]:
                if os.path.isfile(os.path.join(dest_dir, item)):
                    self.assertTrue(item in checksum_file_list,
                                    f"{item}: not in checksum file")
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_follow_dirlink_and_replace_symlinks(self):
        """
        make_copy: follow symlink to directory (dirlink) and replace symlinks
        """
        # Build example directories
        external_dir = UnittestDir(os.path.join(self.wd, "external_dir"))
        external_dir.add("ex4.txt", type="file", content="External file\n")
        external_dir.add("ex5.txt", type="symlink", target="./ex4.txt")
        external_dir.add("subdir2/ex6.txt", type="file",
                         content="Another external file\n")
        external_dir.create()
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt", type="file", content="Example text\n")
        example_dir.add("subdir/ex2.txt", type="file", content="More text\n")
        example_dir.add("subdir/ex3.txt", type="symlink", target="./ex2.txt")
        example_dir.add("subdir/external_dir", type="symlink",
                        target="../../external_dir")
        example_dir.create()
        p = example_dir.path
        # Location for copies
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Make copy
        d = Directory(p)
        dd = make_copy(d, dest_dir, follow_dirlinks=True,
                       replace_symlinks=True)
        self.assertTrue(isinstance(dd, CopyArchiveDirectory))
        self.assertEqual(dd.archive_metadata["type"],
                         "CopyArchiveDirectory")
        # Check resulting directory
        self.assertEqual(dd.path, dest_dir)
        self.assertTrue(os.path.exists(dest_dir))
        expected = ("ex1.txt",
                    "subdir/",
                    "subdir/ex2.txt",
                    "subdir/ex3.txt",
                    "subdir/external_dir/",
                    "subdir/external_dir/ex4.txt",
                    "subdir/external_dir/ex5.txt",
                    "subdir/external_dir/subdir2/",
                    "subdir/external_dir/subdir2/ex6.txt",
                    "ARCHIVE_README.txt",
                    "ARCHIVE_METADATA/",
                    "ARCHIVE_METADATA/manifest",
                    "ARCHIVE_METADATA/symlinks",
                    "ARCHIVE_METADATA/checksums.md5",
                    "ARCHIVE_METADATA/archiver_metadata.json")
        for item in expected:
            self.assertTrue(
                os.path.exists(os.path.join(dest_dir, item)),
                "missing '%s'" % item)
            if not item.startswith("ARCHIVE_METADATA") and \
               item != "ARCHIVE_README.txt":
                self.assertEqual(
                    os.path.getmtime(os.path.join(p, item)),
                    os.path.getmtime(os.path.join(dest_dir, item)),
                    "modification time differs for '%s'" % item)
        # Check extra items aren't present
        for item in dd.walk():
            rel_path = os.path.relpath(item, dest_dir)
            if os.path.isdir(item):
                rel_path = rel_path + "/"
            self.assertTrue(rel_path in expected, "'%s' not expected" % item)
        # Check that dirlink was transformed to an actual directory
        self.assertFalse(
            os.path.islink(os.path.join(dest_dir, "subdir", "external_dir")),
            "dirlink is still a symlink")
        # Check symlinks to files are now files (not links)
        for f in ("subdir/ex3.txt",
                  "subdir/external_dir/ex5.txt",):
            self.assertFalse(os.path.islink(os.path.join(dest_dir, f)),
                            f"{f} is a symlink (but shouldn't be)")
        # Check the manifest contains all the files
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "manifest"),
                  "rt") as fp:
            manifest_file_list = []
            for line in fp:
                manifest_file_list.append(line.rstrip().split("\t")[-1])
            for item in [x for x in expected
                         if not x.startswith("ARCHIVE_METADATA/") and
                         x != "ARCHIVE_README.txt"]:
                self.assertTrue(item in manifest_file_list,
                                f"{item}: not in manifest")
        # Check that checksum file contains all the files
        with open(os.path.join(dest_dir, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            checksum_file_list = []
            for line in fp:
                checksum_file_list.append(line.rstrip().split("  ")[-1])
            for item in [x for x in expected
                         if not x.startswith("ARCHIVE_METADATA/") and
                         x != "ARCHIVE_README.txt"]:
                if os.path.isfile(os.path.join(dest_dir, item)):
                    self.assertTrue(item in checksum_file_list,
                                    f"{item}: not in checksum file")
        # Check MD5 file is properly formatted
        with open(os.path.join(dd.path, "ARCHIVE_METADATA", "checksums.md5"),
                  "rt") as fp:
            for line in fp:
                line = line.rstrip("\n")
                self.assertTrue(re.fullmatch("[a-f0-9]+  .*", line)
                                is not None,
                                f"checksum file: incorrectly formatted "
                                f"line: {line}")

    def test_make_copy_raises_exception_for_existing_partial_copy(self):
        """
        make_copy: raise exception for existing partial copy
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        p = example_dir.path
        # Location for copy
        dest_dir = os.path.join(self.wd, "copies", "example")
        # Add existing .part directory
        os.makedirs(dest_dir + ".part")
        # Make copy
        d = Directory(p)
        self.assertRaises(NgsArchiverException,
                          make_copy,
                          d,
                          dest_dir)

class TestMakeManifestFile(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestMakeManifestFile')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_make_manifest_file(self):
        """
        make_manifest_file: check manifest file is created
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        # Get user and group
        username = getpass.getuser()
        group = grp.getgrgid(pwd.getpwnam(username).pw_gid).gr_name
        # Create manifest file
        manifest_file = make_manifest_file(Directory(example_dir.path),
                                           os.path.join(self.wd, "manifest"))
        self.assertEqual(manifest_file, os.path.join(self.wd, "manifest"))
        self.assertTrue(os.path.exists(manifest_file))
        # Check contents
        expected_lines = ["#Owner\tGroup\tPath",
                          f"{username}\t{group}\tex1.txt",
                          f"{username}\t{group}\tsubdir/",
                          f"{username}\t{group}\tsubdir/ex2.txt"]
        with open(manifest_file, 'rt') as fp:
            for line in fp:
                self.assertTrue(line.rstrip() in expected_lines,
                                f"'{line.rstrip()}': unexpected line")

    def test_make_manifest_file_with_symlinks(self):
        """
        make_manifest_file: check manifest file with symlinks
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/symlink1.txt",type="symlink",target="./ex2.txt")
        example_dir.create()
        # Get user and group
        username = getpass.getuser()
        group = grp.getgrgid(pwd.getpwnam(username).pw_gid).gr_name
        # Create manifest file
        manifest_file = make_manifest_file(Directory(example_dir.path),
                                           os.path.join(self.wd, "manifest"))
        self.assertEqual(manifest_file, os.path.join(self.wd, "manifest"))
        self.assertTrue(os.path.exists(manifest_file))
        # Check contents
        expected_lines = ["#Owner\tGroup\tPath",
                          f"{username}\t{group}\tex1.txt",
                          f"{username}\t{group}\tsubdir/",
                          f"{username}\t{group}\tsubdir/ex2.txt",
                          f"{username}\t{group}\tsubdir/symlink1.txt"]
        with open(manifest_file, 'rt') as fp:
            for line in fp:
                self.assertTrue(line.rstrip() in expected_lines,
                                f"'{line.rstrip()}': unexpected line")

    def test_make_manifest_file_with_broken_symlinks(self):
        """
        make_manifest_file: check manifest file with broken symlinks
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/symlink1.txt",type="symlink",target="missing")
        example_dir.create()
        # Get user and group
        username = getpass.getuser()
        group = grp.getgrgid(pwd.getpwnam(username).pw_gid).gr_name
        # Create manifest file
        manifest_file = make_manifest_file(Directory(example_dir.path),
                                           os.path.join(self.wd, "manifest"))
        self.assertEqual(manifest_file, os.path.join(self.wd, "manifest"))
        self.assertTrue(os.path.exists(manifest_file))
        # Check contents
        expected_lines = ["#Owner\tGroup\tPath",
                          f"{username}\t{group}\tex1.txt",
                          f"{username}\t{group}\tsubdir/",
                          f"{username}\t{group}\tsubdir/ex2.txt",
                          f"{username}\t{group}\tsubdir/symlink1.txt"]
        with open(manifest_file, 'rt') as fp:
            for line in fp:
                self.assertTrue(line.rstrip() in expected_lines,
                                f"'{line.rstrip()}': unexpected line")

    def test_make_manifest_file_with_unresolvable_symlinks(self):
        """
        make_manifest_file: check manifest file with unresolvable symlinks
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir/symlink1.txt",type="symlink",
                        target="./symlink1.txt")
        example_dir.create()
        # Get user and group
        username = getpass.getuser()
        group = grp.getgrgid(pwd.getpwnam(username).pw_gid).gr_name
        # Create manifest file
        manifest_file = make_manifest_file(Directory(example_dir.path),
                                           os.path.join(self.wd, "manifest"))
        self.assertEqual(manifest_file, os.path.join(self.wd, "manifest"))
        self.assertTrue(os.path.exists(manifest_file))
        # Check contents
        expected_lines = ["#Owner\tGroup\tPath",
                          f"{username}\t{group}\tex1.txt",
                          f"{username}\t{group}\tsubdir/",
                          f"{username}\t{group}\tsubdir/ex2.txt",
                          f"{username}\t{group}\tsubdir/symlink1.txt"]
        with open(manifest_file, 'rt') as fp:
            for line in fp:
                self.assertTrue(line.rstrip() in expected_lines,
                                f"'{line.rstrip()}': unexpected line")

    def test_make_manifest_file_follow_dirlinks(self):
        """
        make_manifest_file: check manifest file with dirlinks
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.add("subdir2",type="symlink",target="./subdir")
        example_dir.create()
        # Get user and group
        username = getpass.getuser()
        group = grp.getgrgid(pwd.getpwnam(username).pw_gid).gr_name
        # Create manifest file without following dirlinks
        manifest_file = make_manifest_file(Directory(example_dir.path),
                                           os.path.join(self.wd, "manifest"))
        self.assertEqual(manifest_file, os.path.join(self.wd, "manifest"))
        self.assertTrue(os.path.exists(manifest_file))
        # Check contents
        expected_lines = ["#Owner\tGroup\tPath",
                          f"{username}\t{group}\tex1.txt",
                          f"{username}\t{group}\tsubdir/",
                          f"{username}\t{group}\tsubdir/ex2.txt",
                          f"{username}\t{group}\tsubdir2"]
        manifest_lines = []
        with open(manifest_file, 'rt') as fp:
            for line in fp:
                manifest_lines.append(line.rstrip())
        for line in manifest_lines:
            self.assertTrue(line in expected_lines,
                            f"'{line}': unexpected line in manifest")
        for line in expected_lines:
            self.assertTrue(line in manifest_lines,
                            f"'{line}': missing line in manifest")
        # Create manifest file following dirlinks
        manifest_file = make_manifest_file(Directory(example_dir.path),
                                           os.path.join(self.wd, "manifest2"),
                                           follow_dirlinks=True)
        self.assertEqual(manifest_file, os.path.join(self.wd, "manifest2"))
        self.assertTrue(os.path.exists(manifest_file))
        # Check contents
        expected_lines = ["#Owner\tGroup\tPath",
                          f"{username}\t{group}\tex1.txt",
                          f"{username}\t{group}\tsubdir/",
                          f"{username}\t{group}\tsubdir/ex2.txt",
                          f"{username}\t{group}\tsubdir2/",
                          f"{username}\t{group}\tsubdir2/ex2.txt"]
        manifest_lines = []
        with open(manifest_file, 'rt') as fp:
            for line in fp:
                manifest_lines.append(line.rstrip())
        for line in manifest_lines:
            self.assertTrue(line in expected_lines,
                            f"'{line}': unexpected line in manifest")
        for line in expected_lines:
            self.assertTrue(line in manifest_lines,
                            f"'{line}': missing line in manifest")

    def test_make_manifest_file_noclobber(self):
        """
        make_manifest_file: raises exception if file already exists
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        # Touch existing manifest
        with open(os.path.join(self.wd, "manifest"), "wt") as fp:
            fp.write("")
        self.assertRaises(NgsArchiverException,
                          make_manifest_file,
                          Directory(example_dir.path),
                          os.path.join(self.wd, "manifest"))

class TestMakeVisualTreeFile(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestVisualTreeFile')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_make_visual_tree_file(self):
        """
        make_visual_tree_file: check tree file is created
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        # Create visual tree file
        tree_file = make_visual_tree_file(Directory(example_dir.path),
                                          os.path.join(self.wd, "tree.txt"))
        self.assertEqual(tree_file, os.path.join(self.wd, "tree.txt"))
        self.assertTrue(os.path.exists(tree_file))
        # Check contents
        expected_lines = [f"{os.path.basename(example_dir.path)}",
                          "├── ex1.txt",
                          "└── subdir",
                          "    └── ex2.txt"]
        with open(tree_file, 'rt') as fp:
            for line in fp:
                self.assertTrue(line.rstrip() in expected_lines,
                                f"'{line.rstrip()}': unexpected line")

    def test_make_visual_tree_file_noclobber(self):
        """
        make_visual_tree_file: raises exception if file already exists
        """
        # Build example directory
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="Example text\n")
        example_dir.add("subdir/ex2.txt",type="file",content="More text\n")
        example_dir.create()
        # Touch existing tree file
        with open(os.path.join(self.wd, "tree.txt"), "wt") as fp:
            fp.write("")
        self.assertRaises(NgsArchiverException,
                          make_visual_tree_file,
                          Directory(example_dir.path),
                          os.path.join(self.wd, "tree.txt"))

class TestCheckMakeSymlink(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestGetSize')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_check_make_symlink(self):
        """
        check_make_symlink: is possible
        """
        self.assertTrue(check_make_symlink(self.wd))

class TestCheckCaseSensitiveFileNames(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestCheckCaseSensitiveFileNames')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_check_case_sensitive_filenames(self):
        """
        check_case_sensitive_filenames: are allowed
        """
        self.assertTrue(check_case_sensitive_filenames(self.wd))

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
        self.assertEqual(convert_size_to_bytes('4.5G'),4831838208)
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

class TestFormatBool(unittest.TestCase):

    def test_format_bool(self):
        """
        format_bool: convert True/False to alternative strings
        """
        self.assertEqual(format_bool(True),"yes")
        self.assertEqual(format_bool(False),"no")

    def test_format_bool_custom(self):
        """
        format_bool: use custom alternative strings
        """
        self.assertEqual(format_bool(True,
                                     true="T",
                                     false="F"),
                         "T")
        self.assertEqual(format_bool(False,
                                     true="T",
                                     false="F"),
                         "F")

    def test_format_bool_raises_value_error(self):
        """
        format_bool: raises ValueError for non-boolean input
        """
        self.assertRaises(ValueError,
                          format_bool,
                          "True")
        self.assertRaises(ValueError,
                          format_bool,
                          0)
        self.assertRaises(ValueError,
                          format_bool,
                          None)

class TestGroupCaseSensitiveNames(unittest.TestCase):

    def test_group_case_sensitive_names(self):
        """
        group_case_sensitive_names: file names without paths
        """
        self.assertEqual(list(group_case_sensitive_names(
            ["Ex1.txt", "ex1.txt", "ex2.txt", "Ex2.txt", "ex3.txt"])),
                         [("Ex1.txt", "ex1.txt"),
                          ("Ex2.txt", "ex2.txt")])

    def test_group_case_sensitive_names_with_paths(self):
        """
        group_case_sensitive_names: file names with paths
        """
        self.assertEqual(list(group_case_sensitive_names(
            ["/subdir1/Ex1.txt",
             "/subdir1/ex1.txt",
             "/subdir2/ex2.txt",
             "/subdir2/Ex2.txt",
             "/subdir3/ex3.txt"])),
                         [("/subdir1/Ex1.txt", "/subdir1/ex1.txt"),
                          ("/subdir2/Ex2.txt", "/subdir2/ex2.txt")])

    def test_group_case_sensitive_names_with_different_dirs(self):
        """
        group_case_sensitive_names: file names with different dirs
        """
        self.assertEqual(list(group_case_sensitive_names(
            ["/subdir1/Ex1.txt",
             "/subdir1/ex1.txt",
             "/subdir2/ex2.txt",
             "/subdir2/Ex2.txt",
             "/subdir3/ex1.txt"])),
                         [("/subdir1/Ex1.txt", "/subdir1/ex1.txt"),
                          ("/subdir2/Ex2.txt", "/subdir2/ex2.txt")])

    def test_group_case_sensitive_names_empty_list(self):
        """
        group_case_sensitive_names: empty list as input
        """
        self.assertEqual(list(group_case_sensitive_names([])), [])


class TestTree(unittest.TestCase):

    def setUp(self):
        self.wd = tempfile.mkdtemp(suffix='TestTree')

    def tearDown(self):
        if REMOVE_TEST_OUTPUTS:
            shutil.rmtree(self.wd)

    def test_tree(self):
        """
        tree: regular files and directories
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        example_dir.add("subdir2/ex4.txt",type="file")
        example_dir.create()
        # Expected tree
        expected_tree = ["├── ex1.txt",
                         "├── subdir1",
                         "│   ├── ex2.txt",
                         "│   └── subdir12",
                         "│       └── ex3.txt",
                         "└── subdir2",
                         "    └── ex4.txt"]
        # Generate tree
        example_tree = list(tree(example_dir.path))
        print(example_tree)
        self.assertEqual(example_tree, expected_tree)

    def test_tree_with_symlink(self):
        """
        tree: directory includes symlink
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/ex3.txt",type="symlink",target="./ex2.txt")
        example_dir.create()
        # Expected tree
        expected_tree = ["├── ex1.txt",
                         "└── subdir1",
                         "    ├── ex2.txt",
                         "    └── ex3.txt -> ./ex2.txt"]
        # Generate tree
        example_tree = list(tree(example_dir.path))
        print(example_tree)
        self.assertEqual(example_tree, expected_tree)

    def test_tree_with_broken_symlink(self):
        """
        tree: directory includes broken symlink
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/ex3.txt",type="symlink",target="missing")
        example_dir.create()
        # Expected tree
        expected_tree = ["├── ex1.txt",
                         "└── subdir1",
                         "    ├── ex2.txt",
                         "    └── ex3.txt -> missing"]
        # Generate tree
        example_tree = list(tree(example_dir.path))
        print(example_tree)
        self.assertEqual(example_tree, expected_tree)

    def test_tree_with_dirlink(self):
        """
        tree: directory includes dirlink
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        example_dir.add("subdir2",type="symlink",target="./subdir1")
        example_dir.create()
        p = example_dir.path
        # Expected tree
        expected_tree = ["├── ex1.txt",
                         "├── subdir1",
                         "│   ├── ex2.txt",
                         "│   └── subdir12",
                         "│       └── ex3.txt",
                         "└── subdir2 -> ./subdir1"]
        # Generate tree
        example_tree = list(tree(example_dir.path))
        print(example_tree)
        self.assertEqual(example_tree, expected_tree)

    def test_tree_with_circular_dirlink(self):
        """
        tree: directory includes circular dirlink
        """
        # Build example dir
        example_dir = UnittestDir(os.path.join(self.wd,"example"))
        example_dir.add("ex1.txt",type="file",content="example 1")
        example_dir.add("subdir1/ex2.txt",type="file")
        example_dir.add("subdir1/subdir12/ex3.txt",type="file")
        example_dir.add("subdir2",type="symlink",target="./subdir2")
        example_dir.create()
        p = example_dir.path
        # Expected tree
        expected_tree = ["├── ex1.txt",
                         "├── subdir1",
                         "│   ├── ex2.txt",
                         "│   └── subdir12",
                         "│       └── ex3.txt",
                         "└── subdir2 -> ./subdir2"]
        # Generate tree
        example_tree = list(tree(example_dir.path))
        print(example_tree)
        self.assertEqual(example_tree, expected_tree)
