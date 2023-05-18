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
from pathlib import Path
from bcftbx.Md5sum import md5sum
from auto_process_ngs.command import Command
from .exceptions import NgsArchiveException

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
            raise NgsArchiveException("%s: not a directory" %
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
        size = 0
        for o in self.walk():
            size += os.path.getsize(os.path.join(self._path,o))
        return int(size)

    @property
    def readable(self):
        """
        Check if all files and subdirectories are readable
        """
        return self.check_mode(os.R_OK)

    @property
    def writeable(self):
        """
        Check if all files and subdirectories are writeable
        """
        return self.check_mode(os.W_OK)

    @property
    def external_symlinks(self):
        """
        Check if any symlinks point outside the directory
        """
        for o in self.walk():
            if Path(o).is_symlink():
                target = Path(o).resolve()
                try:
                    Path(target).relative_to(self._path)
                except ValueError:
                    #print("%s: symlink points outside of "
                    #      "directory" % o)
                    return True
        return False

    def check_mode(self,mode):
        """
        Check if all files and subdirectories have 'mode'
        """
        for o in self.walk():
            if not os.access(o,mode):
                return False
        return True

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

    def get_checksums(self,md5file,include_parent=False):
        """
        Write MD5 checksums to a file

        The checksums will be written in the same format
        as produced by the 'md5sum' utility.

        Arguments:
          md5file (str): path for file to write MD5 sums to
          include_parent (str): if True then include the
            parent directory in the paths written to the
            checksum file
        """
        root_dir = os.path.dirname(self._path)
        if include_parent:
            root_dir = os.path.dirname(root_dir)
        with open(md5file,'wt') as fp:
            for o in self.walk():
                if os.path.isfile(o):
                    rel_path = os.path.relpath(o,root_dir)
                    fp.write("%s  %s\n" % (md5sum(o),rel_path))

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

    def walk(self):
        """
        Yields names of all directory and file objects
        """
        for dirpath,dirnames,filenames in os.walk(self._path):
            for name in filenames:
                yield os.path.join(dirpath,name)
            for name in dirnames:
                yield os.path.join(dirpath,name)

    def make_archive(self,fmt,out_dir=None,archive_name=None,
                     include_parent=False):
        """
        Makes an archive file from the directory

        Arguments:
          fmt (str): any of the formats recognised by
            'shutil.make_archive'
          out_dir (str): path to output directory where
            archive file will be written (default: cwd)
          archive_name (str): base name for archive
            file (default: same as directory name)
          include_parent (bool): if True then paths in
            the archive will include the parent
            directory (default: False, don't include
            the parent directory)

        Returns:
          ArchiveFile: object representing the generated
            archive file.
        """
        if not out_dir:
            out_dir = os.getcwd()
        if not archive_name:
            archive_name = os.path.basename(self._path)
        base_name = os.path.join(os.path.abspath(out_dir),
                                 archive_name)
        if not include_parent:
            root_dir = os.path.dirname(self._path)
            base_dir = os.path.basename(self._path)
        else:
            parent_dir = os.path.dirname(self._path)
            root_dir = os.path.dirname(parent_dir)
            base_dir = os.path.join(os.path.basename(parent_dir),
                                    os.path.basename(self._path))
        try:
            return ArchiveFile(shutil.make_archive(base_name,
                                                   fmt,
                                                   root_dir,
                                                   base_dir))
        except Exception as ex:
            raise NgsArchiveException("%s: exception when attempting "
                                      "to make archive with format "
                                      "'%s': %s" % (self._path,fmt,ex))

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

    def make_archive(self,fmt,out_dir=None):
        """
        Makes an archive directory

        Arguments:
          fmt (str): any of the formats recognised by
            'shutil.make_archive'
          out_dir (str): directory under which the archive
            will be created

        Returns:
          ArchiveDirectory: object representing the generated
            archive directory.
        """
        return make_archive_dir(self,fmt,out_dir=out_dir)

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
                raise NgsArchiveException("%s: at least one top-level "
                                          "object is not a directory" %
                                          self._path)
        self._sub_dirs = sub_dirs

    def make_archive(self,fmt,out_dir=None):
        """
        Makes an archive directory

        Arguments:
          fmt (str): any of the formats recognised by
            'shutil.make_archive'
          out_dir (str): directory under which the archive
            will be created

        Returns:
          ArchiveDirectory: object representing the generated
            archive directory.
        """
        return make_archive_dir(self,fmt,out_dir=out_dir,
                                sub_dirs=self._sub_dirs)

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
            raise NgsArchiveException("%s: 'projects.info' not found" %
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

    def make_archive(self,fmt,out_dir=None):
        """
        Makes an archive directory

        Arguments:
          fmt (str): any of the formats recognised by
            'shutil.make_archive'
          out_dir (str): directory under which the archive
            will be created

        Returns:
          ArchiveDirectory: object representing the generated
            archive directory.
        """
        return make_archive_dir(self,fmt,out_dir,
                                sub_dirs=self.project_dirs,
                                misc_objects=self._processing_artefacts,
                                misc_archive_name="processing",
                                extra_files=(self._projects_info,))

class ArchiveFile:
    """
    Class to handle archive files
    """
    def __init__(self,f):
        self._path = os.path.abspath(f)

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
        self._ngsarchive_dir = os.path.join(self.path,'.ngsarchive')
        if not os.path.isdir(self._ngsarchive_dir):
            raise NgsArchiveException("%s: not an archive directory" %
                                      self.path)

    def make_archive(self,*args,**kws):
        """
        Disable the archiving method inherited from base class
        """
        raise NgsArchiveException("%s: can't archive an archive "
                                  "directory" % self.path)

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
            raise NgsArchiveException("%s: destination '%s' doesn't "
                                      "exist or is not a directory"
                                      % (self._path,extract_dir))
        d = os.path.join(extract_dir,
                         os.path.basename(self._path)[:-len('.archive')])
        if os.path.exists(d):
            raise NgsArchiveException("%s: would overwrite existing "
                                      "directory in destination '%s' "
                                      "directory" % (self._path,
                                                     extract_dir))
        # Get metadata
        json_file = os.path.join(self._ngsarchive_dir,
                                 "archive_contents.json")
        with open(json_file,'rt') as fp:
            archive_contents = json.load(fp)
        # Create destination directory
        os.mkdir(d)
        # Copy file artefacts
        for f in archive_contents['files']:
            print("-- copying %s" % f)
            f = os.path.join(self._path,f)
            shutil.copy2(f,d)
        # Unpack individual archive files
        for a in archive_contents['archives']:
            print("-- unpacking %s" % a)
            a = os.path.join(self._path,a)
            ArchiveFile(a).unpack(extract_dir)
        # Do checksum verification on unpacked archive
        if verify:
            print("-- verifying checksums")
            for md5file in [os.path.join(self._path,f)
                            for f in list(
                                    filter(lambda x: x.endswith('.md5')
                                           and x != 'archive.md5',
                                           list(os.listdir(self._path))))]:
                if not verify_checksums(md5file,root_dir=extract_dir):
                   raise NgsArchiveException("%s: checksum verification "
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
        md5file = os.path.join(self._ngsarchive_dir,"archive.md5")
        if not os.path.isfile(md5file):
            raise NgsArchiveException("%s: no MD5 checksum file" % self)
        return verify_checksums(md5file,root_dir=self._path,verbose=True)
        
    def __repr__(self):
        return self._path

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
    except NgsArchiveException:
        pass
    try:
        return MultiProjectRun(d)
    except NgsArchiveException:
        pass
    try:
        return MultiSubdirRun(d)
    except NgsArchiveException:
        pass
    return GenericRun(d)

def make_archive_dir(d,fmt,out_dir=None,sub_dirs=None,
                     misc_objects=None,misc_archive_name="miscellenous",
                     extra_files=None):
    """
    Create an archive directory

    Arguments:
      d (Directory): Directory-like object representing
        the directory to be archived
      fmt (str): any of the formats recognised by
        'shutil.make_archive'
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

    Returns:
      ArchiveDirectory: object representing the generated
        archive directory.
    """
    # Make top level archive dir
    if not out_dir:
        out_dir = os.getcwd()
    archive_dir = os.path.join(os.path.abspath(out_dir),
                               d.basename+".archive")
    os.mkdir(archive_dir)
    # Create .ngsarchive subdir
    ngsarchive_dir = os.path.join(archive_dir,".ngsarchive")
    os.mkdir(ngsarchive_dir)
    # Create manifest file
    manifest = os.path.join(ngsarchive_dir,"manifest.txt")
    with open(manifest,'wt') as fp:
        for o in d.walk():
            o = Path(o)
            owner = Path(o).owner()
            group = Path(o).group()
            fp.write("{owner}\t{group}\t{obj}\n".format(
                owner=owner,
                group=group,
                obj=o.relative_to(d.path)))
    # Record contents
    archive_contents = {
        'archives': [],
        'files': [],
    }
    # Make archive
    if not sub_dirs:
        # Put all content into a single archive
        md5file = os.path.join(archive_dir,"%s.md5" % d.basename)
        Directory.get_checksums(d,md5file)
        a = Directory.make_archive(d,fmt,archive_dir)
        archive_contents['archives'].append(os.path.basename(str(a)))
    else:
        # Make archives for each subdir
        for s in sub_dirs:
            dd = Directory(os.path.join(d.path,s))
            md5file = os.path.join(archive_dir,"%s.md5" % s)
            dd.get_checksums(md5file,include_parent=True)
            a = dd.make_archive(fmt,archive_dir,include_parent=True)
            archive_contents['archives'].append(os.path.basename(str(a)))
        # Put additional miscellaneous artefacts into a separate
        # archive
        if misc_objects:
            tmp_dir = os.path.join(archive_dir,
                                   "tmp_%s" % misc_archive_name,
                                   d.basename)
            os.makedirs(tmp_dir)
            dd = Directory(tmp_dir)
            try:
                for o in misc_objects:
                    o = os.path.join(d.path,o)
                    if os.path.isdir(o):
                        dst = os.path.join(tmp_dir,os.path.basename(o))
                        shutil.copytree(o,dst,symlinks=True)
                    else:
                        shutil.copy2(o,tmp_dir,follow_symlinks=False)
                md5file = os.path.join(archive_dir,
                                       "%s.md5" % misc_archive_name)
                dd.get_checksums(md5file)
                a = dd.make_archive(fmt,archive_dir,
                                    archive_name=misc_archive_name)
                archive_contents['archives'].append(os.path.basename(str(a)))
            finally:
                shutil.rmtree(dd.parent_dir)
        # Copy in extra files
        if extra_files:
            for f in extra_files:
                if not os.path.isabs(f):
                    f = os.path.join(d.path,f)
                shutil.copy2(f,archive_dir)
                archive_contents['files'].append(os.path.basename(f))
    # Checksums for archive contents
    file_list = archive_contents['archives'] + archive_contents['files']
    with open(os.path.join(ngsarchive_dir,"archive.md5"),'wt') as fp:
        for f in file_list:
            fp.write("%s  %s\n" % (md5sum(os.path.join(archive_dir,f)),
                                   f))
    # Write archive contents to JSON file
    json_file = os.path.join(ngsarchive_dir,"archive_contents.json")
    with open(json_file,'wt') as fp:
        json.dump(archive_contents,fp,indent=2)
    return ArchiveDirectory(archive_dir)

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

def du_size(p):
    """
    Return total size of directory in bytes
    """
    du_cmd = Command('du','-s','--block-size=1',p)
    retcode,output = du_cmd.subprocess_check_output()
    if retcode != 0:
        raise Exception("%s: 'du' failed" % p)
    size = int(output.split('\t')[0])
    return size

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
            raise NgsArchiveException("%s: unrecognised size unit "
                                      "'%s'" % (self._path,units))
        for u in UNITS:
            size = float(size)/blocksize
            if units == u:
                return int(size)
