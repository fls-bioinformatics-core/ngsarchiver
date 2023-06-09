#!/usr/bin/env python3
#
#     archive.py: archiving classes and functions
#     Copyright (C) University of Manchester 2023 Peter Briggs
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
import logging
from pathlib import Path
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

class Directory:
    """
    Base class for characterising and handling a directory

    Arguments:
      d (str): path to directory
    """
    def __init__(self,d):
        self._path = os.path.abspath(d)
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
        Return files etc that are not readable
        """
        for o in self.walk():
            if not os.access(o,os.R_OK):
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
    def external_symlinks(self):
        """
        Return symlinks that point outside the directory
        """
        for o in self.walk():
            if Path(o).is_symlink():
                target = Path(o).resolve()
                try:
                    Path(target).relative_to(self._path)
                except ValueError:
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
    def hard_linked_files(self):
        """
        Return files that are hard links

        Yields objects that are files and that have a
        link count greater than one.
        """
        for o in self.walk():
            if os.path.isfile(o) and os.stat(o).st_nlink > 1:
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
            if os.path.isfile(o) and \
               o.split('.')[-1] in ('gz','bz2','zip'):
                yield o

    @property
    def unknown_uids(self):
        """
        Return paths that have unrecognised UIDs
        """
        for o in self.walk():
            try:
                Path(o).owner()
            except KeyError:
                # UID not in the system database
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
            st = os.lstat(o_)
            if st.st_nlink == 1:
                if blocksize:
                    size += st.st_blocks * blocksize
                else:
                    size += st.st_size
            else:
                inode = st.st_ino
                if inode not in inodes:
                    if blocksize:
                        size += st.st_blocks * blocksize
                    else:
                        size += st.st_size
                    inodes.add(inode)
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

    def verify_copy(self,d):
        """
        Verify the directory contents against a copy

        The following checks are performed:

        - All files, directories and symlinks in one directory
          are also present in the other (i.e. none are missing
          or "extra")
        - Directories and symlinks in the source directory are
          are the same types in the copy
        - Symlink targets match between the source and the copy
        - MD5 checksums match for regular files

        Arguments:
          d (str): path to directory to check against
        """
        d = os.path.abspath(d)
        for o in self.walk():
            o_ = os.path.join(d,os.path.relpath(o,self._path))
            if not os.path.exists(o_):
                print("%s: missing from copy" % o)
                return False
            elif os.path.isdir(o):
                if not os.path.isdir(o_):
                    print("%s: not a directory in copy" % o)
                    return False
            elif os.path.islink(o):
                if not os.path.islink(o):
                    print("%s: not a symlink in copy" % o)
                    return False
                if os.readlink(o) != os.readlink(o_):
                    print("%s: symlink target differs in copy" % o)
                    return False
            elif md5sum(o) != md5sum(o_):
                print("%s: MD5 sum differs in copy" % o)
                return False
        for o in Directory(d).walk():
            o_ = os.path.join(self._path,os.path.relpath(o,d))
            if not os.path.exists(o_):
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

    def walk(self):
        """
        Yields names of all directory and file objects
        """
        for dirpath,dirnames,filenames in os.walk(self._path):
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
        return [p for p in self._project_dirs]

    @property
    def processing_artefacts(self):
        """
        List processing artefacts
        """
        return [a for a in self._processing_artefacts]

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

class ArchiveFile:
    """
    Class to handle archive files
    """
    def __init__(self,f):
        self._path = os.path.abspath(f)

    def list(self):
        """
        List the names (paths) stored in the archive
        """
        if self._path.endswith('.tar.gz'):
            with tarfile.open(self._path,'r:gz') as tgz:
                for name in tgz.getnames():
                    yield name
        else:
            raise NotImplementedError("%s: 'list' not implemented for "
                                      "archive type" % self._path)

    def unpack(self,extract_dir=None):
        """
        Unpacks the archive

        Arguments:
          extract_dir (str): directory to extract
            archive into (default: cwd)
        """
        shutil.unpack_archive(self._path,
                              extract_dir)
        
    def __repr__(self):
        return self._path

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
                        logger.warning("%s: '%s' is directory, skipping" %
                                       (self.path,m.path))
                        continue
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
                os.chmod(f,tgzf.mode)
            # Update permissions to include read/write
            os.chmod(f,os.stat(f).st_mode | stat.S_IRUSR | stat.S_IWUSR)
            # Verify MD5 sum
            if md5sum(f) != m.md5:
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
        # Ensure all files etc have read/write permission
        if set_read_write:
            print("-- updating permissions to read-write")
            for o in Directory(d).walk():
                s = os.stat(o)
                os.chmod(o,s.st_mode | stat.S_IRUSR | stat.S_IWUSR)
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
                     misc_objects=None,misc_archive_name="miscellenous",
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
    manifest = os.path.join(ngsarchiver_dir,"manifest.txt")
    with open(manifest,'wt') as fp:
        for o in d.walk():
            o = Path(o)
            try:
                owner = Path(o).owner()
            except (KeyError,FileNotFoundError):
                # Unknown user, fall back to UID
                owner = os.stat(o,follow_symlinks=False).st_uid
            try:
                group = Path(o).group()
            except (KeyError,FileNotFoundError):
                # Unknown group, fall back to GID
                group = os.stat(o,follow_symlinks=False).st_gid
            fp.write("{owner}\t{group}\t{obj}\n".format(
                owner=owner,
                group=group,
                obj=o.relative_to(d.path)))
    # Record contents
    archive_metadata = {
        'name': d.basename,
        'source': d.path,
        'subarchives': [],
        'files': [],
        'user': os.getlogin(),
        'creation_date': None,
        'multi_volume': multi_volume,
        'volume_size': volume_size,
        'compression_level': compresslevel,
        'ngsarchiver_version': get_version(),
    }
    # Make archive
    if not sub_dirs:
        # Put all content into a single archive
        archive_basename = os.path.join(archive_dir,d.basename)
        if not multi_volume:
            a = make_archive_tgz(archive_basename,
                                 d.path,
                                 base_dir=d.basename,
                                 compresslevel=compresslevel)
            archive_metadata['subarchives'].append(os.path.basename(str(a)))
        else:
            a = make_archive_multitgz(archive_basename,
                                      d.path,
                                      base_dir=d.basename,
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
                                     compresslevel=compresslevel)
                archive_metadata['subarchives'].append(
                    os.path.basename(str(a)))
            else:
                a = make_archive_multitgz(archive_basename,
                                          dd.path,
                                          base_dir=prefix,
                                          size=volume_size,
                                          compresslevel=compresslevel)
                for a_ in a:
                    archive_metadata['subarchives'].\
                        append(os.path.basename(str(a_)))
        # Collect miscellaneous artefacts into a separate archive
        if misc_objects:
            # Collect individual artefacts
            file_list = []
            for o in misc_objects:
                o = os.path.join(d.path,o)
                file_list.append(o)
                if os.path.isdir(o):
                    for o_ in Directory(o).walk():
                        file_list.append(os.path.join(o,o_))
            # Make archive(s)
            archive_basename = os.path.join(archive_dir,misc_archive_name)
            prefix = d.basename
            if not multi_volume:
                a = make_archive_tgz(archive_basename,
                                     d.path,
                                     base_dir=prefix,
                                     file_list=file_list,
                                     compresslevel=compresslevel)
                archive_metadata['subarchives'].append(
                    os.path.basename(str(a)))
            else:
                a = make_archive_multitgz(archive_basename,
                                          d.path,
                                          base_dir=prefix,
                                          file_list=file_list,
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
    for a in archive_metadata['subarchives']:
        subarchive = os.path.join(archive_dir,a)
        md5file = os.path.join(archive_dir,
                               "%s.md5" % a[:-len('.tar.gz')])
        with open(md5file,'wt') as fp:
            with tarfile.open(subarchive,'r:gz') as tgz:
                for f in tgz.getnames():
                    ff = os.path.join(d.parent_dir,f)
                    if os.path.isfile(ff):
                        fp.write("%s  %s\n" % (md5sum(ff),f))
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
    Return MD5 digest for a file or stream

    This implements the md5sum checksum generation using he
    hashlib module.

    Arguments:
      f (str): name of the file to generate the checksum from,
        or a file-like object opened for reading in binary
        mode.

    Returns:
      String: MD5 digest for the named file.
    """
    chksum = hashlib.md5()
    close_fp = False
    try:
        fp = open(f,"rb")
        close_fp = True
    except TypeError:
        fp = f
    while True:
        buf = fp.read(MD5_BLOCKSIZE)
        if not buf:
            break
        chksum.update(buf)
    if close_fp:
        fp.close()
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
    """
    with open(md5file,'rt') as fp:
        for line in fp:
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
            except ValueError:
                print("%s: bad checksum line" % line.rstrip('\n'))
        return True

def make_archive_tgz(base_name,root_dir,base_dir=None,ext="tar.gz",
                     compresslevel=6,file_list=None):
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
      file_list (list): specifies a subset of paths to
        include in the archive (default: include all
        paths)

    Returns:
      String: archive name.
    """
    d = Directory(root_dir)
    archive_name = "%s.%s" % (base_name,ext)
    root_dir = d.path
    with tarfile.open(archive_name,'w:gz',compresslevel=compresslevel) \
         as tgz:
        for o in d.walk():
            if file_list and o not in file_list:
                continue
            arcname = os.path.relpath(o,root_dir)
            if base_dir:
                arcname = os.path.join(base_dir,arcname)
            try:
                tgz.add(o,arcname=arcname,recursive=False)
            except Exception as ex:
                raise NgsArchiverException("%s: unable to add '%s' to "
                                           "archive: %s" % (d.path,o,ex))
    return archive_name

def make_archive_multitgz(base_name,root_dir,base_dir=None,
                          size="250M",ext="tar.gz",compresslevel=6,
                          file_list=None):
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
      file_list (list): specifies a subset of paths to
        include in the archive (default: include all
        paths)

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
        if file_list and o not in file_list:
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
                raise NgsArchiverException("%s: object is larger than "
                                           "volume size" % o)
            archive_name = "%s.%02d.%s" % (base_name,indx,ext)
            tgz = tarfile.open(archive_name,'w:gz',
                               compresslevel=compresslevel)
            archive_list.append(archive_name)
        arcname = os.path.relpath(o,root_dir)
        if base_dir:
            arcname = os.path.join(base_dir,arcname)
        try:
            tgz.add(o,arcname=arcname,recursive=False)
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
                os.chmod(o_,o.mode)
                os.utime(o_,(atime,o.mtime))

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
        return int(str(size)[:-1]) * int(math.pow(1024,p))

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
            raise NgsArchiverException("%s: unrecognised size unit "
                                       "'%s'" % (self._path,units))
        for u in UNITS:
            size = float(size)/blocksize
            if units == u:
                return int(size)
