Version History and Changes
===========================

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
