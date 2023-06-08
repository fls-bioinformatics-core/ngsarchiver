=====================================================
ngsarchive: utility for managing BCF NGS data archive
=====================================================

--------
Overview
--------

``ngsarchive`` is a small Python package that provides
a utility for managing the archiving of directories
within the BCF NGS data archive.

Specifically it provides a single executable called
``archiver`` which can be used to:

* Archive and compress sequencing and analysis data
  on a per-run basis
* Interrogate contents of archives
* Restore archived runs and recover subsets of
  archived data

This ``README`` comprises the whole of the usage
documentation.

------------
Installation
------------

The minimal installation is to unpack the ``tar.gz``
archive file containing the Python files; it should be
possible to run the ``archiver`` utility without any
further configuration by simply specifying the path to
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

   archiver archive --force /data/runs/230608_SB1266_0008_AHXXBYA

The specific required and optional arguments will
depend on the subcommand and are outlined in the sections
below; alternatively, specifying ``-h`` or ``--help`` with
a subcommand will bring all available options for that
command (or with no subcommand, all the available
subcommands).

------------------------------
``archive``: create an archive
------------------------------

Makes an archive directory from the specified directory,
for example in its simplest form:

::

   archiver archive /PATH/TO/DIR

The resulting archive directory will be named
``DIR.archive`` and will be created in the current
working directory by default. Note that an existing
archive directory will not be overwritten.

The original directory must pass a number of checks
before the archive is created, to avoid potential
issues with the generated archive (see the section
*Problem situations* below). Specifying the ``-c``
argument performs the checks without the archive
creation; the ``--force`` argument ignores the
results of the checks will always create the archive
directory even if they don't pass.

The original directory is unchanged by the creation
of the archive directory.

The format of the archive directory is described
below in a separate section.


Multi-volume archives
Compresssion levels

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

------------------------
Archive directory format
------------------------

Archive directories are regular directories named with
after the source directory with the suffix ``.archive``
appended.

Within an archive directory there will be:

- one or more ``.tar.gz`` archive files;
- none or more regular files;
- a set of MD5 checksum files with the file extension
  ``.md5``, with one checksum file for each ``.tar.gz``
  and regular file;
- a hidden subdirectory called ``.ngsarchive`` which
  contains additional metadata files (for example a
  JSON file with metadata items, an MD5 file with
  checksums for each of the "visible" archive
  components for integrity verification, and a
  file which lists the original username and group
  associated with each file).

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

The archiver recognises four directory types (which
are determined automatically):

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
- ``ArchiveDirectory`` is an archive directory. The
  archiver will refuse to make an archive of an archive.

------------------
Problem situations
------------------

There are a number of problems that can be encountered
when creating an archive:

- **Unreadable files**: the presence of files or directories
  in the source where the user running the archiving doesn't
  have read access means that those files cannot be included
  in the archive.
- **External symlinks**: these are symbolic links which point
  to files or directories which are outside of the source
  directory, which can potentially result in broken links
  when the symlinks are restored from the archive.
- **Hard links**: depending on the archiving mode, the
  presence of hard links can result in bloating of the
  archive directory, as the hard linked file may be included
  multiple times either within different subarchives or
  within different volumes of a single subarchive (or both).
  The worst case scenario in this case means that both the
  archive and the unpacked version could be substantially
  larger than the source.

There are currently no workarounds within the archiver for
any of these issues. It is recommended that where possible
steps are taken to address them in the source directory prior
to creating the archive; alternatively they can be ignored
using the ``--force`` option of the ``archive`` command
(with the consequences outlined above).

