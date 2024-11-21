===============================================
ngsarchiver: utility for archiving BCF NGS data
===============================================

.. image:: https://zenodo.org/badge/653725091.svg
   :target: https://doi.org/10.5281/zenodo.14024309

.. image:: https://github.com/fls-bioinformatics-core/ngsarchiver/workflows/Python%20CI/badge.svg
   :target: https://github.com/fls-bioinformatics-core/ngsarchiver/actions?query=workflow%3A%22Python+CI%22

--------
Overview
--------

``ngsarchiver`` is a small Python package that
provides a utility for managing the archiving of
directories containing Next Generation Sequencing
(NGS) data within the local data repository of
the Bioinformatics Core Facility (BCF) at the
University of Manchester.

Specifically it provides a single executable called
``archiver`` which can be used to:

* Archive and compress sequencing and analysis data
  on a per-run (i.e. per-directory) basis, to
  produce **compressed archive directories**
* Copy arbitrary directories to an archive location
  without compression or other manipulations, to
  produce **copy archive directories**

In addition for compressed archive directories it
can also be used to:

* Interrogate contents of archived directories
* Restore archived runs and recover subsets of
  archived data

The formats of the two types of archive directory
are described in the relevant sections below.

Note that this ``README`` comprises the whole of the
usage documentation.

----------
Background
----------

``ngsarchiver`` exists primarily as a tool for
archiving data within the BCF datastore.

This datastore exists as a hierarchy of
directories and files residing across a number of
Linux filesystem. The top levels of the hierarchy
act to differentiate data from different years and
which originate from different sequencing platforms
or data sources (e.g. external facilities),
however the exact structure is not relevant within
the context of ``ngsarchiver``: the key point is that
within this hierarchy each distinct sequencing run or
external dataset has its own directory, which is
referred to a "run directory", and archiving is
performed at the run directory level.

"Archiving" in this context implies that the
run directory has reached a point in its lifecycle
where no new data will be added to it in future.

Two types of archiving operation are supported by
``ngsarchiver``, either:

1. Compressing the data where possible (to reduce
   the overall space required to store it), and
   converting to an essentially read-only format
   which can be restored in whole or in part (so
   archived data can be recovered back to its original
   form), or
2. Copying the data to an archive location
   (optionally also transforming it in order to
   allow as full a copy as is possible).

There are broad conventions within the BCF about how
data is structured within each run directory; however,
these conventions can vary over time, between platforms
and even individual analysts. As a result there is a
degree of non-homogeneity across run directories
within the datastore. For this reason ``ngsarchiver``
adopts a largely agnostic approach which makes minimal
assumptions about the internal structure of data within
each run directory. Specifically each run directory
it encounters is automatically classified as one of
three types:

- ``GenericRun`` is a directory with a mixture of files
  and subdirectories at the top-level (and which isn't
  one of the other types); all content is placed in a
  single subarchive.
- ``MultiSubdirRun`` is a directory with only
  subdirectories at the top-level; each subdirectory
  has its own subarchive.
- ``MultiProjectRun`` is a directory with a
  ``projects.info`` file at the top-level along with a
  mixture of other files and subdirectories; each
  project subdirectory has its own subarchive, with the
  non-project content grouped into an additional
  subarchive.

``ngsarchiver`` recognises two additional types:

- ``ArchiveDirectory`` is a compressed archive
  directory created by ``ngsarchiver``
- ``ArchiveCopyDirectory`` is a copy archive
  directory created by ``ngsarchiver``

These last two types cannot be further archived; their
formats are described in the relevant sections below
(*Compressed archive directory format* and
*Copy archive directory format* respectively).

The ``ngsarchiver`` package is intended to provide
a set of simple zero-configuration tools with minimal
dependencies, that can be used to create archive
directories, and to check and restore data from
them. However (in the case of compressed archives) it
should also be possible to verify and recover data
manually with some additional effort using just the
standard Linux command line tools ``tar``, ``gzip``
and ``md5sum``.

Finally, no functionality is provided for the
management of the wider datastore beyond the creation
of the archive directories; it simply creates archive
directories and enables their verification and the
recovery of data from them. It is up to the user to
manage where the generated archive directories are
stored and what should happen to the original run
directories after they have been archived.

-------------
Release notes
-------------

See the `CHANGES file <CHANGES.rst>`_ for version
history.

------------
Installation
------------

The minimal installation is to unpack the ``tar.gz``
archive file containing the Python files; it should be
possible to run the ``archiver`` utility without any
further configuration by specifying the path to
the executable in the unpacked ``bin`` subdirectory.

The only requirement is that ``python3`` should be
available on the ``PATH``.

Alternatively the code can be installed locally,
system-wide, or into a virtual environment using
``pip`` with the appropriate options.

-------------
General usage
-------------

Archiver operations are invoked by specifying the
relevant subcommand, using command lines of the form:

::

   archiver SUBCOMMAND args

for example:

::

   archiver info /data/runs/230608_SB1266_0008_AHXXBYA

The specific required and optional arguments will
depend on the subcommand and are outlined in the sections
below; alternatively, specifying ``-h`` or ``--help`` with
a subcommand will bring all available options for that
command (or with no subcommand, all the available
subcommands).

.. note::

   The archiver is expected to be run by a non-root
   user.

----------------------------------
``info``: characterise directories
----------------------------------

Examines one or more directories and report
characteristics such as total size, type (as outlined
in the section *Archive directory format* below) and
whether the directory contains external and/or broken
symbolic links, hard-linked files and so on.

The simplest form of usage is:

::

   archiver info /PATH/TO/DIR

Multiple directories can be supplied:

::

   archiver info /PATH/TO/DIR1 /PATH/TO/DIR2 ...

Including the ``--list`` argument will provide more
detailed information on any "problem" files found
within the directory, which can then be addressed
prior to archiving.

Alternatively the ``--tsv`` argument will print the
basic information in a single tab-delimited line
for each directory. (Note that this option is not
compatible with the ``--list`` option).

------------------------------
``archive``: create an archive
------------------------------

Makes a compressed archive directory from the specified
directory, for example in its simplest form:

::

   archiver archive /PATH/TO/DIR

The resulting archive directory will be named
``DIR.archive`` and will be created in the current
working directory by default. Note that an existing
archive directory will not be overwritten.

The source directory is unchanged by the creation of
the archive director and must pass a number of checks
before the archive is created. These checks are to
identify potential issues that could arise later with
the generated archive (see the section
*Problem situations* below).

If any check fails then the archive will not be
created unless the ``--force`` argument is also
specified (in which case the archive will be
created regardless of the checks). Specifying the
``-c`` argument performs the checks without the
archive creation.

When ``--force`` is specified then unreadable files
and directories will be omitted from the archive.

The format of the archive directory is described
below in a separate section (see
*Compressed archive directory format*). The archiver
will refuse to make an archive of an archive directory.

By default there is no limit on the size of ``tar.gz``
files created within the archive; the ``--size``
argument allows a limit to be set (e.g.
``--size 50G``), in which case multiple ``tar.gz``
files will be created which will not exceed
this size (aka "multi-volume archives").

By default the archiving uses ``gzip`` compression
level 6 (the same default as Linux ``gzip``);
this is found to give a reasonable trade-off
between speed and amount of compression. The
``--compress-level`` argument allows the
compression level to be explicitly set on the
command line if a higher or lower level of
compression is required.

---------------------------------------
``verify``: verifying archive integrity
---------------------------------------

Checks the integrity of an archive directory created
by the ``archive`` command, for example:

::

   archiver verify /PATH/TO/ARCHIVE_DIR

--------------------------------
``unpack``: unpacking an archive
--------------------------------

Restores a complete copy of the original directory
from an archive directory, for example in its
simplest form:

::

   archiver unpack /PATH/TO/ARCHIVE_DIR

By default the restored copy will be created in the
current working directory. Note that an existing
directory with the same name will not be overwritten.

The restored archive contents are also verified using
their original checksums as part of the unpacking.

The timestamps and permissions of the contents are
also restored (with the caveat that all restored
content will have read-write permission added for the
user unpacking the archive, regardless of the
permissions of the original files).

Ownership information is not restored (unless the
archiving and unpacking operations are both performed
by superuser).

If only a subset of files need to be restored from
the archive then the ``extract`` command is recommended
instead of the full ``unpack``.

-----------------------------------------------------
``compare``: verify unpacked archive against original
-----------------------------------------------------

Compares the contents of two directories against
each other, and is provided to enable a restored
archive to be checked against the original directory
(for example before it is removed from the system):

::

   archiver compare /PATH/TO/DIR1 /PATH/TO/DIR2

The comparison checks for missing and extra files, and
that files have the same checksums.

(Note however that it doesn't check timestamps,
permissions or ownership.)

-------------------------------------
``search``: searching within archives
-------------------------------------

Locates files within one or more achive directories
using shell-style pattern matching based loosely on
that available in the Linux ``find`` command.

For example to search for all gzipped Fastq files:

::

   archiver search -name "*.fastq.gz" /PATH/TO/ARCHIVE_DIR

Using ``-name`` only considers the filename part of
the archived files; alternatively ``-path`` can be
used to include whole paths, for example:

::

   archiver search -path "*/*.fastq.gz" /PATH/TO/ARCHIVE_DIR

Multiple archive directories can also be specified in
a single ``search`` command invocation, in which case
the search will be performed across all the specified
archives.

------------------------------------------------------
``extract``: extracting specific files and directories
------------------------------------------------------

Restores a subset of files from an archive directory
using shell-style pattern matching.

For example to extract all gzipped Fastq files:

::

   archiver extract -name "*.fastq.gz" /PATH/TO/ARCHIVE_DIR

By default the matching files will be extracted to
the current working directory with their leading
paths removed; to keep the full paths for the
extracted files use the ``-k`` option.

Note that existing files with the same name will not
be overwritten.

Note also that the ``-name`` option operates slightly
differently to the ``search`` command, as in this
case it will match both filenames and paths.

Extracted files will have the same timestamps and
permissions as the originals (with the caveat that all
restored content will have read-write permission added
for the user extracting the files, regardless of the
permissions of the originals).

-------------------------------------------------
``copy``: copy a directory to an archive location
-------------------------------------------------

Copies any directory and its contents to another
location for archiving purposes, but without
performing compression (a "copy archive
directory").

At its most basic this is a straight copy of the
source directory, with some metadata files added.

For example:

::

   archiver copy /PATH/TO/SRC_DIR /PATH/TO/ARCHIVES_DIR

This will create a copy of ``SRC_DIR`` as
``/PATH/TO/ARCHIVES_DIR/SRC_DIR`` and verify the
contents against the original version.

The format of the archive directory is described
below in a separate section (see
*Copy archive directory format*). The archiver
will refuse to make an archive of a copy archive
directory.

A directory called ``SRC_DIR`` must not already exist in
the target location.

If the destination directory is not explicitly specified
on the command line then it defaults to the current
directory.

The copy will be aborted unconditionally for the
following cases:

* The original directory contains files or directories
  which cannot be read by the user running the copy
  operation
* The original directory contains files or directories
  where case sensitivity is required to differentiate
  them (e.g. ``myfile.txt`` and ``myFile.txt``), but
  the target filesystem doesn't support case
  sensitive file names.
* The original directory is already some form of
  archive directory

There is no way to override this behaviour; for
unreadable files, the solution is to fix the permissions
in the source directory. For case-sensitive filenames,
either use a target filesystem which does support case
sensitivity, rename the files in the source directory,
or use compressed archives (via the ``archive`` command)
instead.

Other situations will also prevent the copy from being
performed but can be overridden:

* The source directory contains broken or otherwise
  unresolvable symlinks, or symlinks to files outside
  the source directory (unresolvable symlinks include
  things like symlink loops)
* The source directory contains hard linked files
* The source directory contains files or directories
  where the owner or grop UIDs don't match a user on
  the current system.

In these cases the archiver can still be forced to
perform the copy by specifying the ``--force`` option:

* Symlinks will be copied as-is (i.e. preserving their
  targets); this may result in broken symlinks in the
  copy
* Each instance of a hard linked file will be copied as
  a separate file (i.e. hard links are not preserved);
  this may result in multiple identical copies of each
  hard linked file

The ``--check`` option will check for the above problems
without attempting to perform the copy.

There are also a set of options for handling symbolic
links:

* ``--replace-symlinks`` will replace symlinks by
  their targets, provided that the target exists (i.e.
  is not a broken link, see ``--transform-broken-symlinks``
  below) and that it's not a directory (see
  ``--follow-dirlinks``)
* ``--transform-broken-symlinks`` will replace broken
  and unresolvable symbolic links with a file containing
  the name of the link target
* ``--follow-dirlinks`` will replace symlinked
  directories with actual directories, and recursively
  copy the contents of each directory

Symlink replacement may be necessary when copying to a
file system which doesn't support the creation of
symbolic links.

Note that if using ``--follow-dirlinks``, that the
copied directories are not checked before starting the
copy operation, and so may contain "problem" entities
which can cause the operation to fail.

-----------------------------------
Compressed archive directory format
-----------------------------------

Compressed archive directories are regular directories
named after the source directory with the suffix
``.archive`` appended, which are created using the
``archive`` command.

Individual files and directories within the source
directory are bundled together in one or more ``tar``
files which are compressed using ``gzip``, and MD5
checksums are generated both for the original files (so
they can be checked when restored) and for the
archive components (providing an integrity check
on the archive itself).

Within a compressed archive directory there will be:

- one or more ``.tar.gz`` archive files;
- none or more regular files;
- a set of MD5 checksum files with the file extension
  ``.md5``, with one checksum file for each ``.tar.gz``
  file and each regular file (these checksum files
  contain the MD5 sums for each of the files inside
  the ``.tar.gz`` files);
- a subdirectory called ``ARCHIVE_METADATA`` (or a
  hidden subdirectory ``.ngsarchiver``, for legacy
  compressed archives) which contains additional
  metadata files (for example a JSON file with metadata
  items, an MD5 file with checksums for each of the
  "visible" archive components for integrity verification,
  and a file which lists the original username and group
  associated with each file). If files were excluded
  from the archive (e.g. because they were unreadable)
  then these will be listed in an additional file.

The ``.tar.gz`` archives and regular files together
are sufficient to recover the contents of the original
directory; the MD5 checksum files can be used to verify
that the recovered files match the originals when they
are unpacked.

``.tar.gz`` files with the same basename are referred
to as *subarchives*. A subarchive can consist of a
single ``.tar.gz`` file (e.g. ``subdir.tar.gz``), or
a collection of ``.tar.gz`` files with an incrementing
number component (e.g. ``subdir.00.tar.gz``,
``subdir.01.tar.gz`` etc), referred to as a
*multi-volume archive*.

The exact number and naming of the ``.tar.gz`` files
and the present or otherwise of additional regular files
depends on both the archiving mode used to create the
archive directory and the "type" of the source directory.
Multi-volume archives are created when the ``archive``
command is run specifying a maximum volume size, and
are intended to mitigate potential issues with creating
extremely large ``.tar.gz`` archives.

-----------------------------
Copy archive directory format
-----------------------------

Copy archive directories are created using the
``copy`` command. A copy archive will have the same
name as the source directory.

Individual files and directories from the source
directory are copied directly as-is to the archive
directory; by default symbolic links are also copied
as-is, alternatively they may be transformed in the
copy depending on the options specified when the copy
is made.

A copy archive directory will contain an additional
subdirctory created by the archiver called
``ARCHIVE_METADATA``, which in turn contains the
following files:

* ``manifest``: a manifest file listing the owner and
  group associated with the original files
* ``checksums.md5``: MD5 checksum file with checksums
  generated from the source files
* ``archiver_metadata.json``: metadata about the
  archiver, user and creation date of the copy.

Additional files may be present dependent on the
contents of the source directory:

* ``symlinks``: a tab-delimted file listing each of
  the symlinks in the source directory along with
  their targets, and the path that the target
  resolved to (only present if the source contained
  symlinks)
* ``broken_symlinks``: a file with the same format
  as the ``symlinks`` file above, but only containing
  information on the broken symlinks in the source
  directory (only present if the source contained
  broken symlinks)
* ``unresolvable_symlinks``: a tab-delimited file
  listing each of the unresolvable symlinks in the
  source directory along with their targets (only
  present if the source contained unresolvable
  symlinks)

By default a copy archive directory should be same
as the source directory (with the addition of the
``ARCHIVE_METADATA`` subdirectory). However the
copy may differ if any of the ``--replace-symlinks``,
``--transform-broken-symlinks`` or
``--follow-dirlinks`` options were specified (see
the ``copy`` command for more details).

------------------
Problem situations
------------------

There are a number of problems that can be encountered
when creating an archive:

- **Unreadable files**: the presence of files or directories
  in the source where the user running the archiving doesn't
  have read access means that those files cannot be included
  in the archive.
- **Hard links**: depending on the archiving mode, the
  presence of hard links can result in bloating of the
  archive directory, as the hard linked file may be included
  multiple times either within different subarchives or
  within different volumes of a single subarchive (or both).
  The worst case scenario in this case means that both the
  archive and the unpacked version could be substantially
  larger than the source.

Additionally the following situations may cause issues
when archives are restored:

- **External symlinks**: these are symbolic links which point
  to files or directories which are outside of the source
  directory, which can potentially result in broken links
  when the symlinks are restored from the archive.

Other situations are highlighted but are unlikely to cause
problems in themselves when data are restored:

- **Broken symlinks**: these are symbolic links which point
  to targets that no longer exist on the filesystem.
- **Unresolvable symlinks**: these are symbolic links which
  cannot be resolved for some reason (for example if by
  following the link it ends up pointing back to itself).
- **Unknown user IDs**: where the user name is replaced by
  a number (user ID aka UID) which doesn't correspond to a
  known user on the system.

There are currently no workarounds within the archiver for
any of these issues when using the ``archive`` command: it
is recommended that where possible steps are taken to address
them in the source directory prior to creating the archive;
alternatively they can be ignored using the ``--force``
option of the ``archive`` command (with the consequences
outlined above).

Similarly the ``--force`` option is also available for the
archiver's ``copy`` command, however there are also some
mitigations available for some of the issues:

* Working symbolic links can be replaced by their target
  files or directories using the ``--replace-symlinks``
  and ``--follow-dirlinks`` options respectively;
* Broken and unresolvable files can be replaced with
  placeholder files using the
  ``--transform-broken-symlinks`` option.

Note that replacing symbolic links and following directory
links can result in significant bloating of the size of
the copy compared to the original.

-----------------------------------
Compressed archiving example recipe
-----------------------------------

The following bash script provides an example recipe
for archiving to the compressed format:

::

   #!/usr/bin/bash

   # Move to scratch area
   cd /scratch/$USER

   # Set environment variables
   export RUN_DIR=/path/to/run_dir
   export ARCHIVE_DIR=$(pwd)/$(basename $RUN_DIR).archive

   # Check run directory
   archiver archive --check $RUN_DIR
   if [ $? -ne 0 ] ; then
      echo Checks failed >&2
      exit 1
   fi

   # Create archive directory in scratch
   archiver archive $RUN_DIR
   if [ $? -ne 0 ] ; then
      echo Failed to create archive dir >&2
      exit 1
   fi

   # Unpack and check against original
   archiver unpack $ARCHIVE_DIR
   archiver compare $RUN_DIR $(pwd)/$(basename $RUN_DIR)
   if [ $? -ne 0 ] ; then
      echo Unpacked archive differs from original >&2
      exit 1
   fi

   # Relocate archive dir to final location
   mv $ARCHIVE_DIR /path/to/final/dir/

   # Verify relocated archive directory
   archiver verify /path/to/final/dir/$(basename $ARCHIVE_DIR)
   if [ $? -ne 0 ] ; then
      echo Failed to verify archive dir >&2
      exit 1
   fi

----------------------------------------------
Compressed archiving performance: observations
----------------------------------------------

The code was tested on a set of real runs and the
following initial observations have been made:

* Typically we saw compressed archived run
  directories were around 70-80% of the size of
  the original run. A significant number showed
  greater reductions, evenly distributed in the
  range 30-70% of the original size.
* There was no difference in the final size
  between single-volume and multi-volume archives
  in the benchmarking data, indicating that
  choice of volume size doesn't significantly affect
  the amount of compression overall.
* There is relatively little correlation between
  the amount of compression versus the size of
  the original run.
* As a rule of thumb it appeared that the
  percentage of pre-existing compressed content
  in a run predicted the minimum degree of
  overall compression. For example, for a run
  where 80% of the contents are already compressed
  we would expect to see the final archive no
  larger than 80% of the original size (although
  the actual compression could be greater). It
  is not clear why this is, or whether it is
  generally true however.

Data from running the archiver (with the run names
redacted) can be found in the file
`<benchmarking_redacted.tsv>`_; this gives details
of the sequencing platform, total size of the run
(and amount of those data that are already
compressed), the time taken to create archives
for different choices of volume sizes along with
the archive size and compression ratio, and the
time taken to restore the data from each archive.

.. note::

   These data are from running the code on our
   systems at Manchester; it is likely that timings
   etc may differ for other systems.

-------
License
-------

This software is licensed under the 3-Clause BSD
License (BSD-3-Clause).
