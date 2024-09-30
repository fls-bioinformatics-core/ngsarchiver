Version History and Changes
===========================

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
