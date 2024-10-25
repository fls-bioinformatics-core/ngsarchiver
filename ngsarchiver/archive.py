#!/usr/bin/env python3
#
#     archive.py: archiving classes and functions
#     Copyright (C) University of Manchester 2023-2024 Peter Briggs
#

"""
"""

#######################################################################
# Imports
#######################################################################

import os
import shutil
import math
import stat
import json
import time
import pwd
import grp
import time
import tarfile
import hashlib
import fnmatch
import getpass
import tempfile
import logging
import pathlib
from .exceptions import NgsArchiverException
from . import get_version

#######################################################################
# Logger
#######################################################################

logger = logging.getLogger(__name__)
logging.basicConfig(level="INFO",format='%(levelname)s: %(message)s')

#######################################################################
# Module constants
#######################################################################

MD5_BLOCKSIZE = 1024*1024

#######################################################################
# Classes
#######################################################################


class Path(type(pathlib.Path())):
    """
    Wrapper for pathlib.Path class with additional methods

    This class wraps the 'Path' class from the 'pathlib' module
    in order to implement additional methods:

    - is_hardlink: checks if path is a hard linked file
    - is_dirlink: checks if path is a symbolic link to a directory
    - is_broken_symlink: checks if path is a symbolic link where
      the target doesn't exist
    - is_unresolvable_symlink: checks if path is a symbolic link
      which cannot be resolved (for example, if it's a part of a
      symlink loop which ends up pointing back to itself)

    (Use suggestion from https://stackoverflow.com/a/34116756
    to subclass 'Path')
    """

    def __init__(self, *args, **kws):
        super().__init__()

    def owner(self):
        """
        Overrides 'owner' method from base class
        """
        try:
            return super().owner()
        except (KeyError, FileNotFoundError, OSError):
            pass
        # Fall back to UID
        uid = os.lstat(self).st_uid
        try:
            return pwd.getpwuid(uid).pw_name
        except Exception:
            return uid

    def group(self):
        """
        Overrides 'group' method from base class
        """
        try:
            return super().group()
        except (KeyError, FileNotFoundError, OSError):
            pass
        # Fall back to GID
        gid = os.lstat(self).st_gid
        try:
            return grp.getgrgid(gid).gr_name
        except Exception:
            return gid

    def is_dir(self):
        """
        Overrides 'is_dir' method from base class
        """
        if not self.is_unresolvable_symlink():
            return super().is_dir()
        return False

    def is_hardlink(self):
        """
        Returns True if Path is a hard linked file
        """
        if not self.is_symlink() and self.is_file() and \
           os.stat(self).st_nlink > 1:
            return True
        return False

    def is_dirlink(self):
        """
        Returns True if Path is a symbolic link to a directory
        """
        if self.is_symlink() and not self.is_unresolvable_symlink():
            try:
                return self.resolve().is_dir()
            except PermissionError:
                # Don't have permission to check
                # i.e. essentially broken symlink
                return False
        return False

    def is_broken_symlink(self):
        """
        Returns True if Path is a symbolic link with non-existent target
        """
        if self.is_symlink() and not self.is_unresolvable_symlink():
            try:
                return not self.resolve().exists()
            except PermissionError:
                # Don't have permission to check
                # i.e. essentially broken symlink
                return True
        return False

    def is_unresolvable_symlink(self):
        """
        Returns True if Path is a symbolic link that cannot be resolved
        """
        if self.is_symlink():
            try:
                self.resolve()
            except Exception:
                return True
        return False


class Directory:
    """
    Base class for characterising and handling a directory

    Note that this class caches some information (for example
    individual file sizes, whether a file is a symbolic link
    etc). If the contents of the target directory change
    during the lifespan of an instance of this class then it
    is possible that the information returned by the instance
    may not accurately reflect the reality on the file system.

    Arguments:
      d (str): path to directory
    """
    def __init__(self, d):
        self._path = os.path.abspath(d)
        self._cache = {}
        if not os.path.isdir(self._path):
            raise NgsArchiverException("%s: not a directory" %
                                       self._path)

    @property
    def path(self):
        """
        Return the full path to the directory
        """
        return self._path

    @property
    def basename(self):
        """
        Return the directory basename
        """
        return os.path.basename(self._path)

    @property
    def parent_dir(self):
        """
        Return the path to the parent directory
        """
        return os.path.dirname(self._path)
    
    @property
    def size(self):
        """
        Return total size of directory in bytes
        """
        return self.getsize(self.walk())

    @property
    def unreadable_files(self):
        """
        Return full paths to files etc that are not readable
        """
        for o in self.walk():
            try:
                if self._cache[o]["unreadable"]:
                    yield o
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
                self._cache[o]["unreadable"] = (not os.path.islink(o) and
                                                not os.access(o,os.R_OK))
                if self._cache[o]["unreadable"]:
                    yield o

    @property
    def is_readable(self):
        """
        Check if all files and subdirectories are readable
        """
        for o in self.unreadable_files:
            return False
        return True

    @property
    def is_writeable(self):
        """
        Check if all files and subdirectories are writeable
        """
        for o in self.walk():
            if not os.access(o,os.W_OK):
                return False
        return True

    @property
    def symlinks(self):
        """
        Return all symlinks
        """
        for o in self.walk():
            try:
                if self._cache[o]["is_symlink"]:
                    yield o
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
                self._cache[o]["is_symlink"] = Path(o).is_symlink()
                if self._cache[o]["is_symlink"]:
                    yield o

    @property
    def has_symlinks(self):
        """
        Check if directory has any symlinks
        """
        for o in self.symlinks:
            return True
        return False

    @property
    def external_symlinks(self):
        """
        Return symlinks that point outside the directory
        """
        for o in self.symlinks:
            try:
                if self._cache[o]["external_symlink"]:
                    yield o
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
                self._cache[o]["external_symlink"] = False
                try:
                    target = Path(o).resolve()
                    try:
                        Path(target).relative_to(self._path)
                    except ValueError:
                        self._cache[o]["external_symlink"] = True
                except Exception:
                    pass
                if self._cache[o]["external_symlink"]:
                    yield o

    @property
    def has_external_symlinks(self):
        """
        Check if any symlinks point outside of directory
        """
        for o in self.external_symlinks:
            return True
        return False

    @property
    def broken_symlinks(self):
        """
        Return symlinks that point to non-existent targets
        """
        for o in self.symlinks:
            try:
                if self._cache[o]["is_broken_symlink"]:
                    yield o
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
                self._cache[o]["is_broken_symlink"] = \
                            Path(o).is_broken_symlink()
                if self._cache[o]["is_broken_symlink"]:
                    yield o

    @property
    def has_broken_symlinks(self):
        """
        Check if any symlinks point to non-existent targets
        """
        for o in self.broken_symlinks:
            return True
        return False

    @property
    def unresolvable_symlinks(self):
        """
        Return symlinks that cannot be resolved

        Examples include symlink loops (where a symbolic link
        ends up pointing back to itself either directly or via
        intermediate links)
        """
        for o in self.symlinks:
            try:
                if self._cache[o]["is_unresolvable_symlink"]:
                    yield o
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
                self._cache[o]["is_unresolvable_symlink"] = \
                                    Path(o).is_unresolvable_symlink()
                if self._cache[o]["is_unresolvable_symlink"]:
                    yield o

    @property
    def has_unresolvable_symlinks(self):
        """
        Check if any symlinks cannot be resolved
        """
        for o in self.unresolvable_symlinks:
            return True
        return False

    @property
    def dirlinks(self):
        """
        Return all symlinks which point to directories
        """
        for o in self.symlinks:
            try:
                if self._cache[o]["is_dirlink"]:
                    yield o
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
            self._cache[o]["is_dirlink"] = Path(o).is_dirlink()
            if self._cache[o]["is_dirlink"]:
                yield o

    @property
    def has_dirlinks(self):
        """
        Check if directory has any symlink pointing to dirs
        """
        for o in self.dirlinks:
            return True
        return False

    @property
    def hard_linked_files(self):
        """
        Return files that are hard links

        Yields objects that are files and that have a
        link count greater than one.
        """
        for o in self.walk():
            try:
                if self._cache[o]["is_hardlink"]:
                    yield o
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
                self._cache[o]["is_hardlink"] = Path(o).is_hardlink()
                if self._cache[o]["is_hardlink"]:
                    yield o

    @property
    def has_hard_linked_files(self):
        """
        Check if directory contains hard links
        """
        for o in self.hard_linked_files:
            return True
        return False

    @property
    def compressed_files(self):
        """
        Return files that are compressed

        Yields paths to files that end with '.gz', '.bz2'
        or '.zip'
        """
        for o in self.walk():
            try:
                if self._cache[o]["is_compressed_file"]:
                    yield o
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
                self._cache[o]["is_compressed_file"] = \
                                os.path.isfile(o) and \
                                o.split('.')[-1] in ('gz', 'bz2', 'zip')
                if self._cache[o]["is_compressed_file"]:
                    yield o

    @property
    def largest_file(self):
        """
        Return size and path of largest file

        Returns a tuple of (relpath,size)
        """
        max_size = 0
        largest = None
        for o in self.walk():
            s = self.getsize((o,))
            if s > max_size:
                max_size = s
                largest = os.path.relpath(o,self._path)
        return (largest,max_size)

    @property
    def unknown_uids(self):
        """
        Return paths that have unrecognised UIDs
        """
        for o in self.walk():
            try:
                if self._cache[o]["has_unknown_uid"]:
                    yield o
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
                try:
                    pwd.getpwuid(os.lstat(o).st_uid)
                    self._cache[o]["has_unknown_uid"] = False
                except KeyError:
                    # UID not in the system database
                    self._cache[o]["has_unknown_uid"] = True
                if self._cache[o]["has_unknown_uid"]:
                    yield o

    @property
    def has_unknown_uids(self):
        """
        Check if any paths have unrecognised UIDs
        """
        for o in self.unknown_uids:
            return True
        return False

    def getsize(self,file_list,blocksize=512):
        """
        Return total size of all objects in a list

        This method attempts to identify objects with
        the same inode number, and only counts their
        size once (regardless of the number of times
        they appear).
        """
        size = 0
        inodes = set()
        for o in file_list:
            o_ = os.path.join(self._path,o)
            try:
                self._cache[o_]["st_blocks"]
            except KeyError:
                if o not in self._cache:
                    self._cache[o] = {}
                st = os.lstat(o_)
                self._cache[o_]["st_blocks"] = st.st_blocks
                self._cache[o_]["st_size"] = st.st_size
                self._cache[o_]["st_nlink"] = st.st_nlink
                self._cache[o_]["st_ino"] = st.st_ino
            if self._cache[o_]["st_nlink"] > 1:
                inode = self._cache[o_]["st_ino"]
                if inode in inodes:
                    continue
                else:
                    inodes.add(inode)
            if blocksize:
                size += self._cache[o_]["st_blocks"] * blocksize
            else:
                size += self._cache[o_]["st_size"]
        return int(size)

    def check_group(self,group):
        """
        Check if all files and subdirectories belong to a group

        Arguments:
          group (str): name of group that all objects
            must belong to
        """
        for o in self.walk():
            if Path(o).group() != group:
                #print("%s: group '%s'" % (o,Path(o).group()))
                return False
        return True

    def copy(self,dest, replace_symlinks=False,
             transform_broken_symlinks=False,
             follow_dirlinks=False):
        """
        Create a copy of the directory contents

        Arguments:
          dest (str): path for the copy
        replace_symlinks (bool): if True then copy the
          targets pointed to by symbolic links in the source
          directory rather than the links themselves (NB will
          fail for any broken symlinks in the source directory)
        transform_broken_symlinks (bool): if True then replace
          broken symbolic links in the source directory with
          "placeholder" files with the same name in the copy
        follow_dirlinks (bool): if True then transform symbolic
          links to directories into the referent directories
        """
        return make_copy(self,
                         dest,
                         replace_symlinks=replace_symlinks,
                         transform_broken_symlinks=transform_broken_symlinks,
                         follow_dirlinks=follow_dirlinks)

    def verify_checksums(self,md5file):
        """
        Verify the directory contents against MD5 sums

        For each line in the supplied checksum file,
        verify that the specified file is present and
        that the MD5 sum matches.

        Arguments:
          md5file (str): path for file to read MD5 sums from
        """
        return verify_checksums(md5file,
                                root_dir=os.path.dirname(self._path))

    def verify_copy(self,d,follow_symlinks=False,
                    broken_symlinks_placeholders=False):
        """
        Verify the directory contents against a copy

        In default mode the following checks are performed:

        - All files, directories and symlinks in one directory
          are also present in the other (i.e. none are missing
          or "extra")
        - Directories and symlinks in the source directory are
          are the same types in the copy
        - Symlink targets match between the source and the copy
        - MD5 checksums match for regular files

        if 'follow_symlinks' is set to True then the checks
        above are modified to replace symlinks with their
        target files and then checking that the MD5 checksums
        match.

        Note that in this mode:

        - all symlinks are replaced by their targets for
          comparison, regardless of whether they appear in the
          source or the target directories
        - any broken symlinks will cause the verification to
          fail (as they cannot be resolved, but see below)

        If 'broken_symlink_placeholders' is set to True then
        as long as a broken symlink in the source has an
        equivalent "placeholder" file with the same name in
        the target directory then it is considered to be a
        verified match.

        (Note that the reverse is not true i.e. a broken
        symlink in the target cannot match a non-symlink
        file in the source.)

        The 'broken_symlink_placeholders' option operates
        independently of the 'follow_symlinks' option.

        Arguments:
          d (str): path to directory to check against
          follow_symlinks (bool): if True then checks are
            performed against symlink targets rather than
            comparing the symlinks themselves
          broken_symlinks_placeholders (bool): if True then
            checks for broken symlinks in the source
            directory will succeed as long as there is
            an equivalent "placeholder" file in the target
        """
        d = os.path.abspath(d)
        for o in self.walk():
            o_ = os.path.join(d,os.path.relpath(o,self._path))
            if not os.path.lexists(o_):
                print("%s: missing from copy" % o)
                return False
            elif os.path.isdir(o):
                if not os.path.isdir(o_):
                    print("%s: not a directory in copy" % o)
                    return False
            elif os.path.islink(o):
                if follow_symlinks or broken_symlinks_placeholders:
                    if Path(o).is_broken_symlink() \
                       or Path(o).is_unresolvable_symlink():
                        if broken_symlinks_placeholders:
                            if not os.path.lexists(o_):
                                print("%s: no placeholder in copy for "
                                      "broken symlink" % o)
                                return False
                        elif follow_symlinks:
                            print("%s: unable to resolve symlink "
                                  "(following symlinks)" % o)
                            return False
                    elif follow_symlinks:
                        if not Path(o_).resolve().exists():
                            print("%s: unable to resolve symlink "
                                  "(following symlinks)" % o_)
                            return False
                        if md5sum(Path(o).resolve()) != \
                           md5sum(Path(o_).resolve()):
                            print("%s: MD5 sum differs in copy "
                                  "(following symlinks)" % o)
                            return False
                else:
                    if not os.path.islink(o_):
                        print("%s: not a symlink in copy" % o)
                        return False
                    if os.readlink(o) != os.readlink(o_):
                        print("%s: symlink target differs in copy" % o)
                        return False
            elif os.path.islink(o_):
                if follow_symlinks:
                    if md5sum(Path(o).resolve()) != md5sum(Path(o_).resolve()):
                        print("%s: MD5 sum differs in copy "
                              "(following symlinks)" % o)
                        return False
                else:
                    print("%s: is a symlink in copy, not in source" % o)
                    return False
            elif md5sum(o) != md5sum(o_):
                print("%s: MD5 sum differs in copy" % o)
                return False
        for o in Directory(d).walk():
            o_ = os.path.join(self._path,os.path.relpath(o,d))
            if not os.path.lexists(o_):
                print("%s: present in copy only" % o_)
                return False
        return True

    def chown(self,owner=None,group=None):
        """
        Set owner and/or group on directory and contents

        Arguments:
          owner (str): name of user to set owner to (set to
            None to leave owner unchanged)
          group (str): name of group to set group ownership
            too (set to None to leave group unchanged)
        """
        if not owner and not group:
            return
        if owner:
            uid = pwd.getpwnam(owner).pw_uid
        else:
            uid = -1
        if group:
            gid = grp.getgrnam(group).gr_gid
        else:
            gid = -1
        for o in self.walk():
            os.chown(o,uid,gid)
        os.chown(self.path,uid,gid)

    def walk(self, followlinks=False):
        """
        Yields full paths of all directory and file objects

        Arguments:
          followlinks (bool): if True then treat symlinks
            to directories as directories (and descend into
            them); otherwise treat as files (the default)
        """
        for dirpath,dirnames,filenames in os.walk(self._path,
                                                  followlinks=followlinks):
            for name in filenames:
                yield os.path.join(dirpath,name)
            for name in dirnames:
                yield os.path.join(dirpath,name)

    def __repr__(self):
        return self._path

class GenericRun(Directory):
    """
    Characterise a generic run directory

    Arguments:
      d (str): path to directory
    """
    def __init__(self,d):
        Directory.__init__(self,d)

    def make_archive(self,out_dir=None,volume_size=None,
                     compresslevel=6):
        """
        Makes an archive directory

        Arguments:
          out_dir (str): directory under which the archive
            will be created
          volume_size (int/str): if set then creates a
            multi-volume archive with the specified
            volume size
          compresslevel (int): optionally specify the
            gzip compression level (default: 6)

        Returns:
          ArchiveDirectory: object representing the generated
            archive directory.
        """
        return make_archive_dir(self,out_dir=out_dir,
                                volume_size=volume_size,
                                compresslevel=compresslevel)

class MultiSubdirRun(Directory):
    """
    Characterise and archive a multi-subdir directory

    Directory must not contain anything other than subdirs
    at the top level

    Arguments:
      d (str): path to directory
    """
    def __init__(self,d):
        Directory.__init__(self,d)
        sub_dirs = []
        for o in os.listdir(self._path):
            if os.path.isdir(os.path.join(self._path,o)):
                sub_dirs.append(o)
            else:
                raise NgsArchiverException("%s: at least one top-level "
                                           "object is not a directory" %
                                           self._path)
        self._sub_dirs = sub_dirs

    def make_archive(self,out_dir=None,volume_size=None,
                     compresslevel=6):
        """
        Makes an archive directory

        Arguments:
          out_dir (str): directory under which the archive
            will be created
          volume_size (int/str): if set then creates a
            multi-volume archive with the specified
            volume size
          compresslevel (int): optionally specify the
            gzip compression level (default: 6)

        Returns:
          ArchiveDirectory: object representing the generated
            archive directory.
        """
        return make_archive_dir(self,out_dir=out_dir,
                                sub_dirs=self._sub_dirs,
                                volume_size=volume_size,
                                compresslevel=compresslevel)

class MultiProjectRun(Directory):
    """
    Characterise and archive a multi-project directory

    Directory must contain a 'projects.info' file

    Arguments:
      d (str): path to directory
    """
    def __init__(self,d):
        Directory.__init__(self,d)
        projects_info = os.path.join(self._path,"projects.info")
        if not os.path.exists(projects_info):
            raise NgsArchiverException("%s: 'projects.info' not found" %
                                       self._path)
        self._projects_info = projects_info
        project_dirs = []
        with open(self._projects_info,'rt') as fp:
            for line in fp:
                if not line.startswith('#'):
                    p = line.split('\t')[0]
                    if os.path.exists(os.path.join(self._path,p)):
                        project_dirs.append(p)
        for a in os.listdir(self._path):
            if not os.path.isdir(os.path.join(self._path,a)):
                continue
            elif a.startswith('undetermined') and \
                 a not in project_dirs:
                project_dirs.append(a)
        self._project_dirs = project_dirs
        processing_artefacts = []
        for a in os.listdir(self._path):
            if a == "projects.info" or a in self._project_dirs:
                continue
            processing_artefacts.append(a)
        self._processing_artefacts = processing_artefacts

    @property
    def project_dirs(self):
        """
        List project directories
        """
        return sorted([p for p in self._project_dirs])

    @property
    def processing_artefacts(self):
        """
        List processing artefacts
        """
        return sorted([a for a in self._processing_artefacts])

    def make_archive(self,out_dir=None,volume_size=None,
                     compresslevel=6):
        """
        Makes an archive directory

        Arguments:
          out_dir (str): directory under which the archive
            will be created
          volume_size (int/str): if set then creates a
            multi-volume archive with the specified
            volume size
          compresslevel (int): optionally specify the
            gzip compression level (default: 6)

        Returns:
          ArchiveDirectory: object representing the generated
            archive directory.
        """
        return make_archive_dir(self,out_dir,
                                sub_dirs=self.project_dirs,
                                misc_objects=self._processing_artefacts,
                                misc_archive_name="processing",
                                extra_files=(self._projects_info,),
                                volume_size=volume_size,
                                compresslevel=compresslevel)

class ArchiveDirectory(Directory):
    """
    Class to handle archive directories
    """
    def __init__(self,d):
        Directory.__init__(self,d)
        self._ngsarchiver_dir = os.path.join(self.path,'.ngsarchiver')
        if not os.path.isdir(self._ngsarchiver_dir):
            raise NgsArchiverException("%s: not an archive directory" %
                                       self.path)
        self._json_file = os.path.join(self._ngsarchiver_dir,
                                       "archive_metadata.json")
        try:
            with open(self._json_file,'rt') as fp:
                self._archive_metadata = json.loads(fp.read())
        except Exception as ex:
            raise NgsArchiverException("%s: failed to load archive "
                                       "metadata from '%s': %s" %
                                       (self.path,self._json_file,ex))

    @property
    def archive_metadata(self):
        """
        Return dictionary with archive metadata
        """
        return { k : self._archive_metadata[k]
                 for k in self._archive_metadata }

    def list(self):
        """
        List contents of the archive

        Returns each of the members of the archive as an
        'ArchiveDirMember' instance.
        """
        # Members outside archive files
        md5s = {}
        archive_md5sums = os.path.join(self._ngsarchiver_dir,"archive.md5")
        with open(archive_md5sums,'rt') as fp:
            for line in fp:
                f = '  '.join(line.rstrip('\n').split('  ')[1:])
                if f in self._archive_metadata['files']:
                    yield ArchiveDirMember(
                        path=os.path.join(self._archive_metadata['name'],f),
                        subarchive='file',
                        md5=line.split('  ')[0])
        # Members inside archive files
        md5_files = [os.path.join(self.path,f)
                     for f in os.listdir(self.path)
                     if f.endswith('.md5')]
        for f in md5_files:
            subarchive_name = os.path.basename(f)[:-len('.md5')]
            with open(f,'rt') as fp:
                for line in fp:
                    yield ArchiveDirMember(
                        path='  '.join(line.rstrip('\n').split('  ')[1:]),
                        subarchive=os.path.join(self.path,
                                                subarchive_name+'.tar.gz'),
                        md5=line.split('  ')[0])
        # Symlinks
        symlinks_file = os.path.join(self._ngsarchiver_dir,"symlinks.txt")
        if os.path.exists(symlinks_file):
            with open(symlinks_file,'rt') as fp:
                for line in fp:
                    f = '\t'.join(line.split('\t')[:-1])
                    yield ArchiveDirMember(
                        path=f,
                        subarchive=os.path.join(
                            self.path,
                            line.rstrip('\n').split('\t')[-1]),
                        md5=None)

    def search(self,name=None,path=None,case_insensitive=False):
        """
        Search archive contents

        Searches the paths in the archive using the
        supplied shell-style pattern(s) and returns
        the matches as ArchiveDirMember instances.

        Arguments:
          name (str): if supplied then is matched against
            only the filename part of the path for each
            member of the archive (i.e. with leading
            directory name removed)
          path (str): if supplied then is matched against
            the complete path for each member of the
            archive
          case_insensitive (bool): if True then search
            will be case-insensitive (default: False,
            search is case sensitive)
        """
        if not name and not path:
            # Nothing to do
            return
        if case_insensitive:
            if name:
                name = name.lower()
            if path:
                path = path.lower()
        for m in self.list():
            p = m.path
            if case_insensitive:
                p_ = p.lower()
            else:
                p_ = p
            if name:
                if fnmatch.fnmatch(os.path.basename(p_),name):
                    yield m
            if path:
                if fnmatch.fnmatch(p_,path):
                    yield m

    def extract_files(self,name,extract_dir=None,include_path=False):
        """
        Extract a subset of files based on supplied pattern

        Arguments:
          name (str): pattern to match either basename or full
            path of archive members to be extracted
          extract_dir (str): if supplied then extracted files
            will be created relative to this directory (defaults
            to current directory)
          include_path (str): if True then files will be
            extracted with their paths preserved (default is not
            to preserve leading directories)
        """
        if not extract_dir:
            extract_dir = os.getcwd()
        for m in self.search(name=name,path=name):
            if include_path:
                # Destination includes leading path
                f = os.path.join(extract_dir,m.path)
            else:
                # Destination doesn't include leading path
                f = os.path.join(extract_dir,os.path.basename(m.path))
            if os.path.exists(f):
                logger.warning("%s: file '%s' already exists, skipping" %
                               (self.path,f))
                continue
            if m.subarchive == 'file':
                # Top level file
                fsrc = os.path.join(self.path,os.path.basename(m.path))
                print("-- extracting '%s' (%s)" %
                      (m.path,
                       format_size(getsize(fsrc),human_readable=True)))
                os.makedirs(os.path.dirname(f),exist_ok=True)
                shutil.copy2(fsrc,os.path.join(os.path.dirname(f)))
            else:
                # Subarchive member
                with tarfile.open(m.subarchive,'r:gz') as tgz:
                    # Get information on archive member
                    tgzf = tgz.getmember(m.path)
                    if tgzf.isdir():
                        # Skip directories
                        logger.warning("%s: '%s' is directory, skipping" %
                                       (self.path,m.path))
                    elif tgzf.issym():
                        # Regenerate symlinks (rather than extracting)
                        # in case they are broken
                        print("-- extracting '%s' (symbolic link)" %
                              m.path)
                        target = tgzf.linkname
                        # Regenerate link
                        if include_path:
                            os.makedirs(os.path.dirname(f),exist_ok=True)
                        os.symlink(target,f)
                    else:
                        # Extract other archive member types
                        print("-- extracting '%s' (%s)" %
                              (m.path,
                               format_size(tgzf.size,human_readable=True)))
                        if include_path:
                            # Extract with leading path
                            tgz.extract(m.path,path=extract_dir,set_attrs=False)
                        else:
                            # Extract without leading path
                            tgzfp = tgz.extractfile(m.path)
                            with open(f,'wb') as fp:
                                fp.write(tgzfp.read())
                            tgzfp.close()
                # Set initial permissions
                chmod(f,tgzf.mode)
            # Update permissions to include read/write
            if not os.path.islink(f):
                chmod(f,os.stat(f).st_mode | stat.S_IRUSR | stat.S_IWUSR)
            # Verify MD5 sum
            if m.md5 and md5sum(f) != m.md5:
                raise NgsArchiverException("%s: MD5 check failed "
                                           "when extracting '%s'" %
                                           (self.path,m.path))

    def unpack(self,extract_dir=None,verify=True,set_read_write=True):
        """
        Unpacks the archive

        Arguments:
          extract_dir (str): directory to extract
            archive into (default: cwd)
          verify (bool): if True then verify checksums
            for extracted archives (default: True)
          set_read_write (bool): if True then ensure
            extracted files have read/write permissions
            for the user (default: True)

        Returns:
          Directory: appropriate subclass instance of
            Directory class (e.g. GenericRun etc)
            returned by the 'get_rundir_instance'
            function.
        """
        # Determine and check extraction directories
        if not extract_dir:
            extract_dir = os.getcwd()
        extract_dir = os.path.abspath(extract_dir)
        if not os.path.isdir(extract_dir):
            raise NgsArchiverException("%s: destination '%s' doesn't "
                                       "exist or is not a directory"
                                       % (self._path,extract_dir))
        d = os.path.join(extract_dir,
                         os.path.basename(self._path)[:-len('.archive')])
        if os.path.exists(d):
            raise NgsArchiverException("%s: would overwrite existing "
                                       "directory in destination '%s' "
                                       "directory" % (self._path,
                                                      extract_dir))
        # Create destination directory
        os.mkdir(d)
        # Copy file artefacts
        for f in self._archive_metadata['files']:
            print("-- copying %s" % f)
            f = os.path.join(self._path,f)
            shutil.copy2(f,d)
        # Unpack individual archive files
        unpack_archive_multitgz(
            [os.path.join(self._path,a)
             for a in self._archive_metadata['subarchives']],
            extract_dir)
        # Do checksum verification on unpacked archive
        if verify:
            print("-- verifying checksums")
            for md5file in [os.path.join(self._path,f)
                            for f in list(
                                    filter(lambda x: x.endswith('.md5')
                                           and x != 'archive.md5',
                                           list(os.listdir(self._path))))]:
                if not verify_checksums(md5file,root_dir=extract_dir):
                   raise NgsArchiverException("%s: checksum verification "
                                              "failed" % md5file)
            # Check symlinks
            symlinks_file = os.path.join(self._ngsarchiver_dir,"symlinks.txt")
            if os.path.exists(symlinks_file):
                print("-- checking symlinks")
                with open(symlinks_file,'rt') as fp:
                    for line in fp:
                        f = os.path.join(extract_dir,
                                         '\t'.join(line.split('\t')[:-1]))
                        if not os.path.islink(f):
                            raise NgsArchiverException("%s: missing symlink"
                                                       % f)
        # Ensure all files etc have read/write permission
        if set_read_write:
            print("-- updating permissions to read-write")
            for o in Directory(d).walk():
                if not os.path.islink(o):
                    # Ignore symbolic links
                    s = os.stat(o)
                    chmod(o,s.st_mode | stat.S_IRUSR | stat.S_IWUSR)
        # Update the timestamp on the unpacked directory
        shutil.copystat(self.path,d)
        # Return the appropriate wrapper instance
        return get_rundir_instance(d)

    def verify_archive(self):
        """
        Check the integrity of an archive directory

        Verification is performed by checking that the
        MD5 checksums of each component match those
        recorded in the checksum file when the archive
        was created.
        """
        md5file = os.path.join(self._ngsarchiver_dir,"archive.md5")
        if not os.path.isfile(md5file):
            raise NgsArchiverException("%s: no MD5 checksum file" % self)
        checksummed_items = []
        with open(md5file,'rt') as fp:
            for line in fp:
                checksummed_items.append(line.rstrip('\n').split('  ')[1])
        for f in self._archive_metadata['files'] + \
            self._archive_metadata['subarchives']:
            if f not in checksummed_items:
                raise NgsArchiverException("%s: no checksum for '%s'" %
                                           (self,f))
        return verify_checksums(md5file,root_dir=self._path,verbose=True)
        
    def __repr__(self):
        return self._path

class ArchiveDirMember:
    """
    Class representing a member of an archive directory

    Has the following properties:

    - 'path': path of the member within the archive
    - 'archive': subarchive name that contains the
      member
    - 'md5': the MD5 checksum for the member

    Arguments:
      path (str): path of the member
      archive (str): subarchive name (without leading
        directory)
      md5 (str): MD5 checksum
    """
    def __init__(self,path,subarchive,md5):
        self._path = path
        self._subarchive = subarchive
        self._md5 = md5

    @property
    def path(self):
        return self._path

    @property
    def subarchive(self):
        return self._subarchive

    @property
    def md5(self):
        return self._md5

#######################################################################
# Functions
#######################################################################

def get_rundir_instance(d):
    """
    Return an appropriate instance for a directory

    Arguments:
      d (str): path to directory
    """
    try:
        return ArchiveDirectory(d)
    except NgsArchiverException:
        pass
    try:
        return MultiProjectRun(d)
    except NgsArchiverException:
        pass
    try:
        return MultiSubdirRun(d)
    except NgsArchiverException:
        pass
    return GenericRun(d)

def make_archive_dir(d,out_dir=None,sub_dirs=None,
                     misc_objects=None,misc_archive_name="miscellaneous",
                     extra_files=None,volume_size=None,
                     compresslevel=6):
    """
    Create an archive directory

    Arguments:
      d (Directory): Directory-like object representing
        the directory to be archived
      out_dir (str): directory under which the archive
        will be created
      sub_dirs (list): optional, if supplied then
        each specified subdir will be archived separately
        (otherwise all contents will be put into a
        single archive)
      misc_objects (list): optional, if supplied then
        each specified object (i.e. file, directory or
        link) will be archived together in an extra
        archive file (NB ignored unless subdirs have
        also been specified)
      extra_files (list): optional, if supplied then
        each specified file will be copied to the
        archive directory without archiving
      volume_size (int/str): if set then creates a
        multi-volume archive using the specified
        volume size
      compresslevel (int): optionally specify the
        gzip compression level (default: 6)

    Returns:
      ArchiveDirectory: object representing the generated
        archive directory.
    """
    # Multi-volume archive?
    multi_volume = (volume_size is not None)
    # Make top level archive dir
    if not out_dir:
        out_dir = os.getcwd()
    archive_dir = os.path.join(os.path.abspath(out_dir),
                               d.basename+".archive")
    os.mkdir(archive_dir)
    # Create .ngsarchiver subdir
    ngsarchiver_dir = os.path.join(archive_dir,".ngsarchiver")
    os.mkdir(ngsarchiver_dir)
    # Create manifest file
    manifest = make_manifest_file(
        d, os.path.join(ngsarchiver_dir,"manifest.txt"))
    # Record contents
    archive_metadata = {
        'name': d.basename,
        'source': d.path,
        'subarchives': [],
        'files': [],
        'user': getpass.getuser(),
        'creation_date': None,
        'multi_volume': multi_volume,
        'volume_size': volume_size,
        'compression_level': compresslevel,
        'ngsarchiver_version': get_version(),
    }
    # Get list of unreadable objects that can't be archived
    # These will be excluded from the archive dir
    unreadable = list(d.unreadable_files)
    if unreadable:
        logger.warning("Excluding %s unreadable objects from the "
                       "archive" % len(unreadable))
        excluded = os.path.join(ngsarchiver_dir,"excluded.txt")
        with open(excluded,'wt') as fp:
            for f in unreadable:
                fp.write("%s\n" % Path(f).relative_to(d.path))
        logger.warning("Wrote list of excluded objects to '%s'" %
                       excluded)
    # Make archive
    if not sub_dirs:
        # Put all content into a single archive
        archive_basename = os.path.join(archive_dir,d.basename)
        if not multi_volume:
            a = make_archive_tgz(archive_basename,
                                 d.path,
                                 base_dir=d.basename,
                                 exclude_files=unreadable,
                                 compresslevel=compresslevel)
            archive_metadata['subarchives'].append(os.path.basename(str(a)))
        else:
            a = make_archive_multitgz(archive_basename,
                                      d.path,
                                      base_dir=d.basename,
                                      exclude_files=unreadable,
                                      size=volume_size,
                                      compresslevel=compresslevel)
            for a_ in a:
                archive_metadata['subarchives'].append(
                    os.path.basename(str(a_)))
    else:
        # Make archives for each subdir
        for s in sub_dirs:
            dd = Directory(os.path.join(d.path,s))
            archive_basename = os.path.join(archive_dir,dd.basename)
            prefix = os.path.join(os.path.basename(dd.parent_dir),
                                  dd.basename)
            if not multi_volume:
                a = make_archive_tgz(archive_basename,
                                     dd.path,
                                     base_dir=prefix,
                                     exclude_files=unreadable,
                                     compresslevel=compresslevel)
                archive_metadata['subarchives'].append(
                    os.path.basename(str(a)))
            else:
                a = make_archive_multitgz(archive_basename,
                                          dd.path,
                                          base_dir=prefix,
                                          exclude_files=unreadable,
                                          size=volume_size,
                                          compresslevel=compresslevel)
                for a_ in a:
                    archive_metadata['subarchives'].\
                        append(os.path.basename(str(a_)))
        # Collect miscellaneous artefacts into a separate archive
        if misc_objects:
            # Collect individual artefacts
            misc_file_list = []
            for o in misc_objects:
                o = os.path.join(d.path,o)
                if o in unreadable:
                    # Skip unreadable files etc
                    continue
                misc_file_list.append(o)
                if os.path.isdir(o):
                    for o_ in Directory(o).walk():
                        misc_file_list.append(o_)
            # Make archive(s)
            archive_basename = os.path.join(archive_dir,misc_archive_name)
            prefix = d.basename
            if not multi_volume:
                a = make_archive_tgz(archive_basename,
                                     d.path,
                                     base_dir=prefix,
                                     include_files=misc_file_list,
                                     compresslevel=compresslevel)
                archive_metadata['subarchives'].append(
                    os.path.basename(str(a)))
            else:
                a = make_archive_multitgz(archive_basename,
                                          d.path,
                                          base_dir=prefix,
                                          include_files=misc_file_list,
                                          size=volume_size,
                                          compresslevel=compresslevel)
                for a_ in a:
                    archive_metadata['subarchives'].\
                        append(os.path.basename(str(a_)))
        # Copy in extra files
        if extra_files:
            for f in extra_files:
                if not os.path.isabs(f):
                    f = os.path.join(d.path,f)
                shutil.copy2(f,archive_dir)
                archive_metadata['files'].append(os.path.basename(f))
    # Generate checksums for each subarchive
    symlinks = {}
    for a in archive_metadata['subarchives']:
        subarchive = os.path.join(archive_dir,a)
        md5file = os.path.join(archive_dir,
                               "%s.md5" % a[:-len('.tar.gz')])
        with open(md5file,'wt') as fp:
            with tarfile.open(subarchive,'r:gz') as tgz:
                for f in tgz.getnames():
                    ff = os.path.join(d.parent_dir,f)
                    if os.path.islink(ff):
                        symlinks[f] = a
                    elif os.path.isfile(ff):
                        fp.write("%s  %s\n" % (md5sum(ff),f))
    # Record symlinks
    if symlinks:
        symlinks_file = os.path.join(ngsarchiver_dir,"symlinks.txt")
        with open(symlinks_file,'wt') as fp:
            for s in symlinks:
                fp.write("%s\t%s\n" % (s,symlinks[s]))
    # Checksums for archive contents
    file_list = archive_metadata['subarchives'] + archive_metadata['files']
    with open(os.path.join(ngsarchiver_dir,"archive.md5"),'wt') as fp:
        for f in file_list:
            fp.write("%s  %s\n" % (md5sum(os.path.join(archive_dir,f)),
                                   f))
    # Update the creation date
    archive_metadata['creation_date'] = time.strftime("%Y-%m-%d %H:%M:%S")
    # Write archive contents to JSON file
    json_file = os.path.join(ngsarchiver_dir,"archive_metadata.json")
    with open(json_file,'wt') as fp:
        json.dump(archive_metadata,fp,indent=2)
    # Update the attributes on the archive directory
    shutil.copystat(d.path,archive_dir)
    return ArchiveDirectory(archive_dir)

def md5sum(f):
    """
    Return MD5 digest for a file

    This implements the md5sum checksum generation using the
    hashlib module.

    Arguments:
      f (str): name of the file to generate the checksum for

    Returns:
      String: MD5 digest for the named file.
    """
    chksum = hashlib.md5()
    with open(f,"rb") as fp:
        while True:
            buf = fp.read(MD5_BLOCKSIZE)
            if not buf:
                break
            chksum.update(buf)
    return chksum.hexdigest()

def verify_checksums(md5file,root_dir=None,verbose=False):
    """
    Verify MD5 checksums from a file

    Arguments:
      md5file (str): path to file with MD5 checksums
      root_dir (str): if supplied then will be
        prepended to paths in the checksum file
      verbose (bool): if True then report files
        being checked (default: False)

    Returns:
      Boolean: True if all MD5 checks pass, fail if not

    Raises:
      NgsArchiverException: if the checksum file has
        issues (e.g. badly-formatted lines)
    """
    with open(md5file,'rt') as fp:
        for lineno,line in enumerate(fp,start=1):
            try:
                chksum,path = line.rstrip('\n').split('  ')
                if verbose:
                    print("-- checking MD5 sum for %s" % path)
                if root_dir:
                    path = os.path.join(root_dir,path)
                if not os.path.exists(path):
                    print("%s: missing, can't verify checksum" % path)
                    return False
                if md5sum(path) != chksum:
                    print("%s: checksum verification failed" % path)
                    return False
            except ValueError as ex:
                raise NgsArchiverException("%s (L%d): bad checksum line "
                                           "'%s': %s" % (md5file,
                                                         lineno,
                                                         line.rstrip('\n'),
                                                         ex))
        return True

def make_archive_tgz(base_name,root_dir,base_dir=None,ext="tar.gz",
                     compresslevel=6,include_files=None,
                     exclude_files=None):
    """
    Make a 'gztar' archive from the contents of a directory

    Arguments:
      base_name (str): base name of output archive file
        (can include leading path)
      root_dir (str): path to the directory which will
        archived; archive contents will be relative to
        this path
      base_dir (str): optional path to be prepended to
        the paths of the archive contents
      ext (str): optionally explicitly specify the archive
        file extension (default: 'tar.gz')
      compresslevel (int): optionally specify the
        gzip compression level (default: 6)
      include_files (list): specifies a subset of paths
        to include in the archive (default: include all
        paths)
      exclude_files (list): specifies a subset of paths
        to exclude from the archive, if they would
        otherwise have been included

    Returns:
      String: archive name.
    """
    d = Directory(root_dir)
    archive_name = "%s.%s" % (base_name,ext)
    root_dir = d.path
    with tarfile.open(archive_name,'w:gz',compresslevel=compresslevel) \
         as tgz:
        for o in d.walk():
            if include_files and o not in include_files:
                continue
            if exclude_files and o in exclude_files:
                continue
            arcname = os.path.relpath(o,root_dir)
            if base_dir:
                arcname = os.path.join(base_dir,arcname)
            try:
                tgz.add(o,arcname=arcname,recursive=False)
            except PermissionError as ex:
                logger.warning("%s: unable to add '%s' to "
                               "archive: %s (ignored)" % (d.path,o,ex))
            except Exception as ex:
                raise NgsArchiverException("%s: unable to add '%s' to "
                                           "archive: %s" % (d.path,o,ex))
    return archive_name

def make_archive_multitgz(base_name,root_dir,base_dir=None,
                          size="250M",ext="tar.gz",compresslevel=6,
                          include_files=None,exclude_files=None):
    """
    Make a multi-volume 'gztar' archive of directory contents

    Creates a set of one or more tar.gz files ("volumes")
    which together store the contents of the specified
    directory.

    Each volume is named 'BASE_NAME.NN.tar.gz', where
    'NN' is a volume number, for example:

    ``example.01.tar.gz``

    The 'size' arguments sets an approximate limit on the
    size of each volume, with new volumes being created
    each time the previous one exceeds this limit.

    Arguments:
      base_name (str): base name of output archive file
        (can include leading path)
      root_dir (str): path to the directory which will
        archived; archive contents will be relative to
        this path
      base_dir (str): optional path to be prepended to
        the paths of the archive contents
      size (int/str): specifies the approximate volume
        size; if an integer then is a number of bytes,
        otherwise can be a string of the form '1G', '100M'
        etc (default: '250M')
      ext (str): optionally explicitly specify the archive
        file extension (default: 'tar.gz')
      compresslevel (int): optionally specify the
        gzip compression level (default: 6)
      include_files (list): specifies a subset of paths
        to include in the archive (default: include all
        paths)
      exclude_files (list): specifies a subset of paths
        to exclude from the archive, if they would
        otherwise have been included

    Returns:
      List: list of the archive volumes.
    """
    d = Directory(root_dir)
    max_size = convert_size_to_bytes(size)
    indx = 0
    archive_name = None
    archive_list = []
    tgz = None
    for o in d.walk():
        if include_files and o not in include_files:
            continue
        if exclude_files and o in exclude_files:
            continue
        try:
            size = getsize(o)
        except Exception as ex:
            raise NgsArchiverException("%s: unable to get size of '%s' "
                                       "for multi-volume archiving: %s"
                                       % (d.path,o,ex))
        if archive_name and (getsize(archive_name) >
                             (max_size - size)):
            indx += 1
            tgz.close()
            tgz = None
        if not tgz:
            if size > max_size:
                logger.warning("%s: object is larger than volume size "
                               "for multi-volume archive (%s > %s)" %
                               (o,format_size(size,human_readable=True),
                                format_size(max_size,human_readable=True)))
            archive_name = "%s.%02d.%s" % (base_name,indx,ext)
            tgz = tarfile.open(archive_name,'w:gz',
                               compresslevel=compresslevel)
            archive_list.append(archive_name)
        arcname = os.path.relpath(o,root_dir)
        if base_dir:
            arcname = os.path.join(base_dir,arcname)
        try:
            tgz.add(o,arcname=arcname,recursive=False)
        except PermissionError as ex:
            logger.warning("%s: unable to add '%s' to "
                           "multi-volume archive: %s (ignored)"
                           % (d.path,o,ex))
        except Exception as ex:
            raise NgsArchiverException("%s: unable to add '%s' to "
                                       "multi-volume archive: %s"
                                       % (d.path,o,ex))
    if tgz:
        tgz.close()
    return archive_list

def unpack_archive_multitgz(archive_list,extract_dir=None):
    """
    Unpack a multi-volume 'gztar' archive

    Arguments:
      archive_list (list): list of archive volumes to
        unpack
      extract_dir (str): specifies directory to unpack
        volumes into (default: current directory)
    """
    if extract_dir is None:
        extract_dir = os.getcwd()
    for a in archive_list:
        print("Extracting %s..." % a)
        # Use this rather than 'tgz.extractall()' to deal
        # with potential permissions issues (for example
        # if a read-only directory appears in multiple
        # volumes)
        with tarfile.open(a,'r:gz',errorlevel=1) as tgz:
            for o in tgz:
                try:
                    tgz.extract(o,path=extract_dir,set_attrs=False)
                except Exception as ex:
                    print("Exception extracting '%s' from '%s': %s"
                          % (o.name,a,ex))
                    raise ex
    atime = time.time()
    for a in archive_list:
        print("Updating attributes from %s..." % a)
        with tarfile.open(a,'r:gz',errorlevel=1) as tgz:
            for o in tgz:
                o_ = os.path.join(extract_dir,o.name)
                chmod(o_,o.mode)
                utime(o_,(atime,o.mtime))

def make_copy(d, dest, replace_symlinks=False,
              transform_broken_symlinks=False,
              follow_dirlinks=False):
    """
    Make a copy of a directory

    Arguments:
      d (Directory): Directory-like object representing
        the directory to be copied
      dest (str): path to directory into which the directory
        contents will be copied
      replace_symlinks (bool): if True then copy the targets
        pointed to by symbolic links in the source directory
        rather than the links themselves (NB will fail for
        any broken symlinks in the source directory)
      transform_broken_symlinks (bool): if True then replace
        broken symbolic links in the source directory with
        "placeholder" files with the same name in the copy
      follow_dirlinks (bool): if True then transform symbolic
        links to directories into the referent directories
    """
    # Create temporary (.part) directory
    dest = str(Path(dest).absolute())
    temp_copy = dest + ".part"
    if Path(temp_copy).exists():
        raise NgsArchiverException(f"{d}: found existing partial copy "
                                   "'{temp_copy}' (remove before retrying)")
    # Do the copy
    os.makedirs(temp_copy)
    print(f"- copying to {temp_copy}...")
    print(f"- replace working symlinks?....{format_bool(replace_symlinks)}")
    print(f"- transform broken symlinks?...{format_bool(transform_broken_symlinks)}")
    print(f"- follow directory symlinks?...{format_bool(follow_dirlinks)}")
    print(f"- starting...")
    has_errors = False
    for o in d.walk(followlinks=follow_dirlinks):
        src = Path(o)
        dst = os.path.join(temp_copy, src.relative_to(d.path))
        logger.debug(f"Handling {src} -> {dst}")
        try:
            if src.is_symlink():
                logger.debug(f"-> {src} is some form of symlink")
                # Handle all types of symlinks
                if not (replace_symlinks or
                        transform_broken_symlinks or
                        follow_dirlinks):
                    # Direct copy (no replace/transform/follow)
                    logger.debug(f"-> direct copy symlink")
                    shutil.copy2(src, dst, follow_symlinks=False)
                elif src.is_dirlink():
                    # Dirlink
                    logger.debug(f"-> {src} is dirlink")
                    if follow_dirlinks:
                        # Make directory
                        logger.debug(f"-> creating equivalent dir in copy")
                        os.makedirs(dst)
                    elif replace_symlinks:
                        logger.error(f"{src}: cannot replace dirlink")
                        has_errors = True
                    else:
                        # Direct copy (no replace/transform/follow)
                        logger.debug(f"-> direct copy dirlink")
                        shutil.copy2(src, dst, follow_symlinks=False)
                elif src.is_broken_symlink() or src.is_unresolvable_symlink():
                    # Broken or unresolvable symlink
                    logger.debug(f"-> {src} is broken or unresolvable symlink")
                    if transform_broken_symlinks:
                        logger.debug(f"-> transforming broken/unresolvable "
                                     "symlink")
                        with open(dst, "wt") as fp:
                            fp.write(f"{os.readlink(o)}\n")
                            logger.debug(f"-> updating stat for broken link")
                            # Workaround as shutil.copystat doesn't work
                            # for broken or unresolvable symlinks
                            st = os.lstat(src)
                            os.utime(dst, times=(st.st_atime, st.st_mtime),
                                     follow_symlinks=False)
                    elif replace_symlinks:
                        logger.error(f"{src}: cannot replace broken or "
                                     "unresolvable symlink")
                        has_errors = True
                else:
                    # Standard symlink
                    logger.debug(f"-> {src} is a standard symlink")
                    if replace_symlinks:
                        replace_src = src.resolve()
                        logger.debug(f"-> replacing with referent file "
                                     f"{replace_src}")
                        shutil.copy2(replace_src, dst,
                                     follow_symlinks=True)
                    else:
                        logger.debug(f"-> direct copy of symlink")
                        shutil.copy2(src, dst,
                                     follow_symlinks=False)
            elif src.is_dir():
                # Directory
                logger.debug(f"-> {src} is a directory")
                logger.debug(f"-> creating equivalent dir in copy")
                os.makedirs(dst)
            else:
                logger.debug(f"-> {src} is a simple file")
                logger.debug(f"-> direct copy of file")
                shutil.copy2(src, dst, follow_symlinks=False)
        except Exception as ex:
            logger.error(f"Copy: exception handling '{src}': {ex}")
            has_errors = True
    # Fail if errors occurred in copying
    if has_errors:
        raise NgsArchiverException(f"{d}: failed to make complete copy in "
                                   f"'{temp_copy}'")
    # Update the modification times for directories
    # after copying files
    for o in d.walk(followlinks=follow_dirlinks):
        src = Path(o)
        if src.is_dir():
            dst = os.path.join(temp_copy, src.relative_to(d.path))
            shutil.copystat(src, dst, follow_symlinks=False)
    print(f"- copy completed")
    # Verify against the original
    print("- starting verification...")
    if d.verify_copy(temp_copy,
                     follow_symlinks=replace_symlinks,
                     broken_symlinks_placeholders=transform_broken_symlinks):
        print(f"- verified copy in '{temp_copy}'")
    else:
        raise NgsArchiverException(f"{d}: failed to verify copy in "
                                   f"'{temp_copy}'")
    # Create archive metadata
    metadata_dir = os.path.join(temp_copy, "ARCHIVE_METADATA")
    os.mkdir(metadata_dir)
    # Create a manifest file
    manifest = make_manifest_file(d, os.path.join(metadata_dir, "manifest"),
                                  follow_dirlinks=follow_dirlinks)
    print(f"- created manifest file '{manifest}'")
    # Create symlinks file
    if d.has_symlinks:
        symlinks_file = os.path.join(metadata_dir, "symlinks")
        with open(symlinks_file, 'wt') as fp:
            for o in d.symlinks:
                o = Path(o)
                if not o.is_unresolvable_symlink():
                    fp.write(f"{o.relative_to(d.path)}\t"
                             f"{os.readlink(o)}\t"
                             f"{o.resolve()}\n")
                else:
                    fp.write(f"{o.relative_to(d.path)}\t"
                             f"{os.readlink(o)}\t"
                             f"?\n")
    # Create broken symlinks file
    if d.has_broken_symlinks:
        broken_symlinks_file = os.path.join(metadata_dir, "broken_symlinks")
        with open(broken_symlinks_file, 'wt') as fp:
            for o in d.broken_symlinks:
                o = Path(o)
                fp.write(f"{o.relative_to(d.path)}\t"
                         f"{os.readlink(o)}\t"
                         f"{o.resolve()}\n")
    # Create unresolvable symlinks file
    if d.has_unresolvable_symlinks:
        unresolvable_symlinks_file = os.path.join(metadata_dir,
                                                  "unresolvable_symlinks")
        with open(unresolvable_symlinks_file, 'wt') as fp:
            for o in d.unresolvable_symlinks:
                o = Path(o)
                fp.write(f"{o.relative_to(d.path)}\t"
                         f"{os.readlink(o)}\n")
    # Create checksum file
    md5sums = os.path.join(metadata_dir, "checksums.md5")
    with open(md5sums, 'wt') as fp:
        for o in d.walk(followlinks=follow_dirlinks):
            o = Path(o)
            if o.is_dir() or o.is_dirlink():
                continue
            elif o.is_broken_symlink() or o.is_unresolvable_symlink():
                if transform_broken_symlinks:
                    md5 = md5sum(os.path.join(temp_copy,
                                              o.relative_to(d.path)))
                else:
                    continue
            elif o.is_symlink():
                if replace_symlinks:
                    o_ = o.resolve()
                    md5 = md5sum(o_)
                else:
                    continue
            else:
                md5 = md5sum(o)
            fp.write(f"{md5}  {o.relative_to(d.path)}\n")
    print(f"- created checksums file '{md5sums}'")
    # Add JSON file with archiver info
    archive_metadata = {
        'name': d.basename,
        'source': d.path,
        'user': getpass.getuser(),
        'creation_date': time.strftime("%Y-%m-%d %H:%M:%S"),
        'replace_symlinks': format_bool(replace_symlinks),
        'transform_broken_symlinks': format_bool(transform_broken_symlinks),
        'follow_dirlinks': format_bool(follow_dirlinks),
        'ngsarchiver_version': get_version(),
    }
    # Write archive contents to JSON file
    json_file = os.path.join(metadata_dir, "archiver_metadata.json")
    with open(json_file, 'wt') as fp:
        json.dump(archive_metadata, fp, indent=2)
    # Move to final location
    shutil.move(temp_copy, dest)
    shutil.copystat(d.path, dest)
    print(f"- moved final copy to {dest}")
    return Directory(dest)

def make_manifest_file(d, manifest_file, follow_dirlinks=False):
    """
    Create a 'manifest' file for a directory

    A manifest file lists the owner and group for
    each of the file objects found in the target
    directory.

    Arguments:
      d (Directory): directory to generate the
        manifest for
      manifest_file (str): path to the file to
        write the manifest data to
      follow_dirlinks (bool): if True then transform
        symbolic links to directories into the
        referent directories (and include files and
        directories underneath)
    """
    if Path(manifest_file).exists():
        raise NgsArchiverException(f"{manifest_file}: already exists")
    with open(manifest_file, 'wt') as fp:
        for o in d.walk(followlinks=follow_dirlinks):
            o = Path(o)
            owner = Path(o).owner()
            group = Path(o).group()
            fp.write("{owner}\t{group}\t{obj}\n".format(
                owner=owner,
                group=group,
                obj=o.relative_to(d.path)))
    return manifest_file

def check_make_symlink(d):
    """
    Check if it's possible to make a symbolic link
    """
    if not Path(d).is_dir():
        raise OSError(f"{d}: is not a directory")
    try:
        with tempfile.TemporaryDirectory(dir=d) as tmpdir:
            test_file = os.path.join(tmpdir, "test_file")
            with open(test_file, "wt") as fp:
                fp.write("")
            os.symlink(test_file, os.path.join(tmpdir, "test_symlink"))
            return True
    except Exception as ex:
        print(f"check_make_symlink failed: {ex}")
    return False

def getsize(p,blocksize=512):
    """
    Return the size of a filesystem object

    Uses the 'lstat' function so symlinks will have
    their actual size reported (rather than the size
    of the target).

    Should be used in preference to 'os.path.getsize'.

    Arguments:
      blocksize (int): if supplied then size will
        the number of blocks multipled by the
        supplied value (default: 512)
    """
    if blocksize:
        return os.lstat(p).st_blocks * blocksize
    return os.lstat(p).st_size

def chmod(path,mode):
    """
    Wrapper for os.chmod which ignores symlinks
    """
    if os.path.islink(path):
        return
    return os.chmod(path,mode)

def utime(path,*args,**kwds):
    """
    Wrapper for os.utime which ignores symlinks
    """
    if os.path.islink(path):
        return
    return os.utime(path,*args,**kwds)

def convert_size_to_bytes(size):
    """
    Return generic size string converted to bytes

    Arguments:
      size (str): can be an integer or a string of the
        form '1.4G' etc
    """
    try:
        return int(str(size))
    except ValueError:
        units = str(size)[-1].upper()
        p = "KMGTP".index(units) + 1
        return int(float(str(size)[:-1]) * math.pow(1024,p))

def format_size(size,units='K',human_readable=False):
    """
    Return size (in bytes) converted to specified format
    """
    UNITS = ['k','m','g','t','p']
    blocksize = 1024
    if human_readable:
        for u in UNITS:
            size = float(size)/blocksize
            if size < blocksize:
                return "%.1f%s" % (size,u.upper())
    elif units:
        units = units.lower()
        if units not in UNITS:
            raise ValueError("Unrecognised size unit '%s'" % units)
        for u in UNITS:
            size = float(size)/blocksize
            if units == u:
                return int(size)

def format_bool(b,true="yes",false="no"):
    """
    Return "yes" or "no" (or custom values) based on boolean

    Arguments:
      b (boolean): Boolean value
      true (str): string to return if boolean is True
        (default: "yes")
      false (str): string to return if boolean is False
        (default: "no")

    Returns:
      String: string corresponding to True or False value.

    Raises:
      ValueError: if supplied value is not a boolean.
    """
    if b is True:
        return true
    elif b is False:
        return false
    else:
        raise ValueError("%r: not a boolean" % b)
