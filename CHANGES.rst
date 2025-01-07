Version History and Changes
===========================

---------------------------
Version 1.8.3 (2025-01-07)
---------------------------

* Bug fix for ``archive`` command when a multi-subdir or
  multi-project has one or more empty top-level subdirs
  (would result in either invalid or missing ``tar.gz``
  archives for empty subdirs, so source run directory
  could not be completely recovered) (PR #62)

---------------------------
Version 1.8.2 (2024-12-16)
---------------------------

* Bug fix for ``unpack`` command when unpacking an archive
  with filenames that differ only by case (would incorrectly
  fail even when the destination file system was able to
  differentiate filenames differing only by case) (PR #60)

---------------------------
Version 1.8.1 (2024-12-13)
---------------------------

* Bug fix to prevent ``extract`` command attempting to extract
  the same files multiple times (PR #57)
* Bug fix to handle non-standard compressed archive directory
  names (i.e. not in ``SOURCE.archive`` format) when unpacking
  (PR #58)

---------------------------
Version 1.8.0 (2024-12-11)
---------------------------

* Additional metadata items stored for compressed and copy
  archive directories (include size of the soure directory
  and whether it included symlinks etc) (PR #53)
* ``unpack`` command checks if destination file system can
  support symlink creation and/or case-sensitive naming, if
  either of these are required to unpack a compressed
  archive (PR #54)
* ``info`` command also reports on "unwriteable" files (i.e.
  files that the current user doesn't have write permissions
  for) (PR #55)

---------------------------
Version 1.7.0 (2024-12-02)
---------------------------

* Updated the command line help and documentation for the
  archiver subcommands (PR #45)
* Add unpacking information to the ``ARCHIVE_README`` files
  for compressed archive directories (PR #46)
* Bug fix to copy verification for copy archive directories
  (PR #48)
* Add ``ARCHIVE_TREE.txt`` files to compressed archive
  directories (visual tree representation of the source
  directory contents) (PR #49)
* Rename ``ARCHIVE_README`` files to ``ARCHIVE_README.txt``
  (PR #50)
* Add ``ARCHIVE_FILELIST.txt`` files to compressed archive
  directories (plain text lists of paths of the source
  directory contents) (PR #51)

---------------------------
Version 1.6.0 (2024-11-28)
---------------------------

* Add ``ARCHIVE_README`` files to compressed and copy archive
  directories (PR #43)
* Add ``source_date`` as metadata item in compressed and copy
  archive directories (PR #42)

---------------------------
Version 1.5.0 (2024-11-22)
---------------------------

* Add trailing slash to directory paths in archive manifest
  files (to distinguish from regular files and links) (PR #40)

---------------------------
Version 1.4.0 (2024-11-21)
---------------------------

* Add new ``CopyArchiveDirectory`` class for identifying and
  handling copy archives, and update the ``info``, ``verify``
  and ``compare`` archiver commands to work with copy archives
  using this class (PR #38)
* ``verify_copy`` method of the ``Directory`` class updated
  to allow specific paths to be excluded from the comparison
  (PR #37)
* Update ``manifest`` files to include a header line (PR #36)
* Update the compressed archive directory metadata structure
  to be consistent with copy archive directories (legacy
  compressed archives created with earlier versions can still
  be recognised) (PR #35)

---------------------------
Version 1.3.1 (2024-11-01)
---------------------------

* Add Zenodo badge to README file (PR #32)
* Update README to distinguish between "compressed archives"
  and "copy archives" (PR #33)

---------------------------
Version 1.3.0 (2024-11-01)
---------------------------

* Implement detection of file and directory names where case
  sensitive is significant, and check that destination file
  system can handle these names when performing ``copy`` (PR #30)
* Add caching of some properties in the ``Directory`` class
  to improve efficiency when running some commands (PR #29)

---------------------------
Version 1.2.1 (2024-10-24)
---------------------------

* Fix bug in ``Path`` class when handling symbolic links to
  inaccesible files, and treat these as broken symlinks (PR #27)

---------------------------
Version 1.2.0 (2024-10-23)
---------------------------

* Fix minor formatting issues for stdout from ``copy`` command
  (PR #25)
* Update ``info`` command to take multiple directories on the
  command line, and implement new ``--tsv`` option to output
  information for each directory as a single tab-delimited line
  (PR #24)
* Fix unit tests for ``walk`` method of ``Directory`` class
  when handling dirlinks (were non-deterministic) (PR #23, PR #22)

---------------------------
Version 1.1.0 (2024-10-21)
---------------------------

* New ``symlinks`` method for ``Directory`` class (detects all
  symbolic links) (PR #16)
* Add options to transform symlinks (``--replace-symlinks``,
  ``--transform-broken-symlinks`` and ``--follow-dirlinks``) on
  ``copy`` command (PR #17)
* Check if symlink creation is possible on target area for ``copy``
  command before starting copy (PR #18)
* Updates to detect and handle unresolvable symlinks (e.g. symlink
  loops) for ``copy`` command and ``make_copy`` function (PR #19)

---------------------------
Version 1.0.2 (2024-09-30)
---------------------------

* Fix bug in ``verify_copy`` method of the ``Directory`` class when
  verifying symlinks (PR #14)

---------------------------
Version 1.0.1 (2024-09-27)
---------------------------

* Fix error with ``os.lstat`` not recognising the ``follow_symlinks``
  argument (PR #11)
* ``archiver`` returns error message and non-zero status if no
  sub-command is supplied on the command line (PR #12)

---------------------------
Version 1.0.0 (2024-09-26)
---------------------------

* Initial version.
