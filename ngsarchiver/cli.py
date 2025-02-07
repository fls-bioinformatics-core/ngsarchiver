#!/usr/bin/env python3
#
#     cli.py: command line interface classes and functions
#     Copyright (C) University of Manchester 2023-2025 Peter Briggs
#

"""
"""

#######################################################################
# Imports
#######################################################################

import sys
import os
import logging
from argparse import ArgumentParser
from .archive import ArchiveDirectory
from .archive import CopyArchiveDirectory
from .archive import check_make_symlink
from .archive import check_case_sensitive_filenames
from .archive import convert_size_to_bytes
from .archive import format_size
from .archive import format_bool
from .archive import get_rundir_instance
from . import get_version

#######################################################################
# Logger
#######################################################################

logger = logging.getLogger(__name__)
logging.basicConfig(level="INFO",format='%(levelname)s: %(message)s')

#######################################################################
# CLI exit codes
#######################################################################

class CLIStatus(object):
    OK = 0
    ERROR = 1

#######################################################################
# Functions
#######################################################################

def main(argv=None):
    """
    Implements the command line interface for archiver operations

    Arguments:
      argv (list): list of command line arguments (defaults
        to sys.argv if not supplied)

    Returns:
      Integer: status code from CLIStatus.
    """
    # Get command line arguments if not supplied
    if argv is None:
        argv = sys.argv[1:]

    # Top-level parser
    p = ArgumentParser(description="NGS data archiving utility")
    p.add_argument('--version',action='version',version=get_version())

    # Subcommands
    s = p.add_subparsers(dest='subcommand')

    # 'info' command
    parser_info = s.add_parser('info',
                               help="get information on a directory")
    parser_info.add_argument('dir', nargs="+",
                             help="path to directory")
    mutex = parser_info.add_mutually_exclusive_group()
    mutex.add_argument('--list',action='store_true',
                       help="list unreadable files, external symlinks "
                       "etc")
    mutex.add_argument('--tsv',action='store_true',
                       help="report details for each directory as a "
                       "single line of tab-delimited values")

    # 'archive' command
    parser_archive = s.add_parser('archive',
                                  help="make compressed archive of a "
                                  "directory")
    parser_archive.add_argument('dir',
                                help="path to directory")
    parser_archive.add_argument('-o','--out-dir',metavar='OUT_DIR',
                                action='store',dest='out_dir',
                                help="create archive under OUT_DIR "
                                "(default: current directory)")
    parser_archive.add_argument('-s','--volume-size',metavar='SIZE',
                                action='store',dest='volume_size',
                                help="create multi-volume subarchives "
                                "with each subarchiver no greater "
                                "than SIZE (e.g. '100M', '25G' etc)")
    parser_archive.add_argument('-l','--compress-level',metavar='LEVEL',
                                action='store',dest='compresslevel',
                                type=int,default=6,
                                help="specify gzip compression level "
                                "used when creating archives (1-9, "
                                "higher value means more compression) "
                                "(default: 6)")
    parser_archive.add_argument('-g','--group',action='store',
                                help="set the group on the final "
                                "archive")
    parser_archive.add_argument('-c','--check',action='store_true',
                                help="check for and warn about potential "
                                "issues; don't perform archiving")
    parser_archive.add_argument('--force',action='store_true',
                                help="ignore issues with links, UIDS and/or "
                                "archive volume sizes and perform archiving "
                                "anyway")

    # 'copy' command
    parser_copy = s.add_parser('copy',
                               help="make copy archive of a directory")
    parser_copy.add_argument('dir',
                             help="path to directory")
    parser_copy.add_argument('dest_dir', nargs="?",
                             help="create copy under 'dest_dir' "
                             "(default: current directory)")
    parser_copy.add_argument('-c','--check',action='store_true',
                             help="check for and warn about potential "
                             "issues; don't perform copying")
    parser_copy.add_argument('-r','--replace-symlinks',action='store_true',
                             help="replace symbolic links with their "
                             "target (default is to copy links as-is; will "
                             "fail for broken links unless '-t' option "
                             "is also specified; will fail for dirlinks "
                             "unless '-f' option is also specified)")
    parser_copy.add_argument('-f','--follow-dirlinks',action='store_true',
                             help="replace dirlinks (symbolic links to "
                             "directories) with actual directories, and "
                             "recursively copy the contents of those "
                             "directories")
    parser_copy.add_argument('-t','--transform-broken-symlinks',
                             action='store_true',
                             help="replace broken and unresolvable symbolic "
                             "links with placeholder files (default is to "
                             "copy broken and unresolvable links as-is)")
    parser_copy.add_argument('--force',action='store_true',
                             help="ignore issues and perform "
                             "copy anyway (may result in incomplete "
                             "or problematic copy)")

    # 'verify' command
    parser_verify = s.add_parser('verify',
                                  help="verify integrity of an archive "
                                 "directory")
    parser_verify.add_argument('archive',
                               help="path to compressed or copy archive "
                               "directory")

    # 'unpack' command
    parser_unpack = s.add_parser('unpack',
                                  help="extract all files from a "
                                 "compressed archive")
    parser_unpack.add_argument('archive',
                               help="path to compressed archive directory")
    parser_unpack.add_argument('-o','--out-dir',metavar='OUT_DIR',
                               action='store',dest='out_dir',
                               help="unpack archive under OUT_DIR "
                               "(default: current directory)")
    parser_unpack.add_argument('--copy-permissions',
                               action='store_true', dest='copy_permissions',
                               help="copy the permissions stored in the "
                               "archive to the extracted files (default: "
                               "set permissions to read-write)")

    # 'search' command
    parser_search = s.add_parser('search',
                                 help="search within compressed archives")
    parser_search.add_argument('archives',
                               nargs="+",metavar="archive",
                               help="path to archive directory")
    parser_search.add_argument('-name',metavar='pattern',action='store',
                               help="pattern to match base of file names")
    parser_search.add_argument('-path',metavar='pattern',action='store',
                               help="pattern to match full paths")
    parser_search.add_argument('-i',dest='case_insensitive',
                               action='store_true',
                               help="use case-insensitive pattern matching "
                               "(default is to respect case)")

    # 'extract' command
    parser_extract = s.add_parser('extract',
                                  help="extract specific files from "
                                  "compressed archive")
    parser_extract.add_argument('archive',
                                help="path to compressed archive directory")
    parser_extract.add_argument('-name',action='store',
                                help="name or pattern to match base "
                                "of file names to be extracted")
    parser_extract.add_argument('-o','--out-dir',metavar='OUT_DIR',
                                action='store',dest='out_dir',
                                help="extract files into OUT_DIR "
                                "(default: current directory)")
    parser_extract.add_argument('-k','--keep-path',
                                action='store_true',
                                help="preserve the leading directory "
                                "paths when extracting files (default "
                                "is to drop leading paths)")

    # 'compare' command
    parser_compare = s.add_parser('compare',
                                  help="check if two directories have the "
                                  "same contents")
    parser_compare.add_argument('dir1',
                                help="path to first directory")
    parser_compare.add_argument('dir2',
                                help="path to second directory")

    # Parse the arguments
    args = p.parse_args(argv)
    
    # 'Info' subcommand
    if args.subcommand == "info":
        if args.tsv:
            header = ["Path",
                      "Type",
                      "Size",
                      "Largest_file",
                      "Compressed",
                      "Compressed%",
                      "Unreadable?",
                      "Unwritable?",
                      "Symlinks?",
                      "Dirlinks?",
                      "External?",
                      "Broken?",
                      "Unresolvable?",
                      "Hardlinks?",
                      "Unknown_uids?",
                      "Case_sensitive?"]
            print("\t".join(header))
        for d in args.dir:
            try:
                d = get_rundir_instance(d)
            except Exception as ex:
                logger.error(ex)
                return CLIStatus.ERROR
            size = d.size
            largest_file, largest_file_size = d.largest_file
            compressed_file_size = d.getsize(d.compressed_files)
            if args.tsv:
                line = [d.path,
                        d.__class__.__name__,
                        format_size(size,human_readable=True),
                        format_size(largest_file_size, human_readable=True),
                        format_size(compressed_file_size,human_readable=True),
                        f"{float(compressed_file_size)/float(size)*100.0:.1f}" \
                        if not (compressed_file_size == 0 and size == 0) else "0.0",
                        format_bool(not d.is_readable),
                        format_bool(not d.is_writable),
                        format_bool(d.has_symlinks),
                        format_bool(d.has_dirlinks),
                        format_bool(d.has_external_symlinks),
                        format_bool(d.has_broken_symlinks),
                        format_bool(d.has_unresolvable_symlinks),
                        format_bool(d.has_hard_linked_files),
                        format_bool(d.has_unknown_uids),
                        format_bool(d.has_case_sensitive_filenames)]
                print("\t".join([str(x) for x in line]))
                continue
            print(f"Path: {d.path}")
            print(f"Type: {d.__class__.__name__}")
            print(f"Size: {format_size(size,human_readable=True)}")
            print(f"Largest file: "
                  f"{format_size(largest_file_size, human_readable=True)} "
                  f"({largest_file})")
            if compressed_file_size > 0.0:
                print(
                    f"Compressed contents: "
                    f"{format_size(compressed_file_size,human_readable=True)} "
                    f"[{float(compressed_file_size)/float(size)*100.0:.1f}%]")
            else:
                print("Compressed contents: 0 [0.0%]")
            if isinstance(d,ArchiveDirectory) or \
               isinstance(d,CopyArchiveDirectory):
                for item in d.archive_metadata:
                    print(f"-- {item}: {d.archive_metadata[item]}")
                    continue
            if args.list:
                print("Unreadable files:")
                is_readable = True
                for f in d.unreadable_files:
                    print(f"-- {f}")
                    is_readable = False
                if is_readable:
                    print("-- no unreadable files")
                print("Unwritable files:")
                is_writable = True
                for f in d.unwritable_files:
                    print(f"-- {f}")
                    is_writable = False
                if is_writable:
                    print("-- no unwritable files")
                print("Symlinks: %s" % format_bool(d.has_symlinks))
                print("Dirlinks:")
                has_dirlinks = False
                for s in d.dirlinks:
                    print(f"-- {s}")
                    has_dirlinks = True
                print("External symlinks:")
                has_external_symlinks = False
                for s in d.external_symlinks:
                    print(f"-- {s}")
                    has_external_symlinks = True
                if not has_external_symlinks:
                    print("-- no external symlinks")
                print("Broken symlinks:")
                has_broken_symlinks = False
                for s in d.broken_symlinks:
                    print(f"-- {s}")
                    has_broken_symlinks = True
                if not has_broken_symlinks:
                    print("-- no broken symlinks")
                print("Unresolvable symlinks:")
                has_unresolvable_symlinks = False
                for s in d.unresolvable_symlinks:
                    print(f"-- {s}")
                    has_unresolvable_symlinks = True
                if not has_unresolvable_symlinks:
                    print("-- no unresolvable symlinks")
                print("Hard linked files:")
                has_hard_links = False
                for f in d.hard_linked_files:
                    print(f"-- {f}")
                    has_hard_links = True
                if not has_hard_links:
                    print("-- no hard linked files")
                print("Unknown UIDs:")
                has_unknown_uids = False
                for f in d.unknown_uids:
                    print(f"-- {f}")
                    has_unknown_uids = True
                if not has_unknown_uids:
                    print("-- no files with unknown UIDs")
                print("Case-sensitive filenames:")
                has_case_sensitive_filenames = False
                for file_group in d.case_sensitive_filenames:
                    print(f"-- {file_group[0]}")
                    for f in file_group[1:]:
                        print(f"   {f}")
                    has_case_sensitive_filenames = True
                if not has_case_sensitive_filenames:
                    print("-- no files with case-sensitive filenames")
            else:
                print(f"Unreadable files     : "
                      f"{format_bool(not d.is_readable)}")
                print(f"Unwritable files    : "
                      f"{format_bool(not d.is_writable)}")
                print(f"Symlinks             : {format_bool(d.has_symlinks)}")
                print(f"Dirlinks             : {format_bool(d.has_dirlinks)}")
                print(f"External symlinks    : "
                      f"{format_bool(d.has_external_symlinks)}")
                print(f"Broken symlinks      : "
                      f"{format_bool(d.has_broken_symlinks)}")
                print(f"Unresolvable symlinks: "
                      f"{format_bool(d.has_unresolvable_symlinks)}")
                print(f"Hard linked files    : "
                      f"{format_bool(d.has_hard_linked_files)}")
                print(f"Unknown UIDs         : "
                      f"{format_bool(d.has_unknown_uids)}")
                print(f"Case-sensitive files : "
                      f"{format_bool(d.has_case_sensitive_filenames)}")
            if len(args.dir) > 1:
                print("")
        return CLIStatus.OK

    # 'Archive' subcommand
    if args.subcommand == "archive":
        try:
            d = get_rundir_instance(args.dir)
        except Exception as ex:
            logger.error(ex)
            return CLIStatus.ERROR
        if isinstance(d, ArchiveDirectory) or \
           isinstance(d, CopyArchiveDirectory):
            logger.critical(f"{d.path}: can't make archive from an "
                            "existing archive directory")
            return CLIStatus.ERROR
        size = d.size
        largest_file = d.largest_file
        check_status = 0
        print("Checking %s..." % d)
        print("-- type        : %s" % d.__class__.__name__)
        print("-- size        : %s" % format_size(size,
                                                  human_readable=True))
        print("-- largest file: %s" % format_size(largest_file[1],
                                                  human_readable=True))
        is_readable = d.is_readable
        print(f"-- unreadable files     : {format_bool(not is_readable)}")
        has_external_symlinks = d.has_external_symlinks
        print(f"-- external symlinks    : {format_bool(has_external_symlinks)}")
        has_broken_symlinks = d.has_broken_symlinks
        print(f"-- broken symlinks      : {format_bool(has_broken_symlinks)}")
        has_unresolvable_symlinks = d.has_unresolvable_symlinks
        print(f"-- unresolvable symlinks: "
              f"{format_bool(has_unresolvable_symlinks)}")
        has_unknown_uids = d.has_unknown_uids
        print(f"-- unknown UIDs         : {format_bool(has_unknown_uids)}")
        has_hard_linked_files = d.has_hard_linked_files
        print(f"-- hard linked files    : {format_bool(has_hard_linked_files)}")
        if not is_readable:
            msg = "Unreadable files and/or directories detected"
            logger.critical(msg)
            if args.check:
                check_status = 1
            else:
                return CLIStatus.ERROR
        if has_external_symlinks or \
           has_broken_symlinks or \
           has_unknown_uids:
            msg = "Symlink and/or UID issues detected"
            if args.check:
                logger.warning(msg)
                check_status = 1
            elif args.force:
                msg += " (ignored"
                if has_external_symlinks or \
                   has_broken_symlinks or \
                   has_unresolvable_symlinks:
                    msg += "; broken/unresolvable and/or external links " \
                           "will be archived as-is"
                msg += ")"
                logger.warning(msg)
            else:
                logger.critical(msg)
                return CLIStatus.ERROR
        if has_hard_linked_files and args.volume_size:
            msg = "Hard links detected with multi-volume archiving"
            if args.check:
                logger.warning(msg)
                check_status = 1
            elif args.force:
                logger.warning("%s (ignored; hard-linked files will "
                               "appear multiple times and size of the "
                               "archive may be inflated)" % msg)
            else:
                logger.critical(msg)
                return CLIStatus.ERROR
        volume_size = args.volume_size
        if volume_size:
            if convert_size_to_bytes(volume_size) > size:
                msg = "Requested volume size (%s) larger than " \
                "uncompressed size (%s) archive" % \
                (format_size(convert_size_to_bytes(volume_size),
                             human_readable=True),
                 format_size(convert_size_to_bytes(size),
                             human_readable=True))
                if args.check:
                    logger.warning(msg)
                    check_status = 1
                elif args.force:
                    logger.warning("%s (ignored; multi-volume archiving "
                                   "will be disabled)" % msg)
                    volume_size = None
                else:
                    logger.critical(msg)
                    return CLIStatus.ERROR
            elif convert_size_to_bytes(volume_size) < largest_file[1]:
                msg = "Requested volume size (%s) smaller than largest " \
                      "file size (%s)" % \
                      (format_size(convert_size_to_bytes(volume_size),
                                   human_readable=True),
                       format_size(largest_file[1],
                                   human_readable=True))
                if args.check:
                    logger.warning(msg)
                    check_status = 1
                elif args.force:
                    logger.warning("%s (ignored; larger volumes will "
                                   "be created when required)" % msg)
                else:
                    logger.critical(msg)
                    return CLIStatus.ERROR
        dest_dir = args.out_dir
        if not dest_dir:
            dest_dir = os.getcwd()
        dest_dir = os.path.join(dest_dir,
                                "%s.archive" % d.basename)
        if os.path.exists(dest_dir):
            msg = "%s: archive directory already exists" % dest_dir
            if args.check:
                logger.warning(msg)
                check_status = 1
            else:
                logger.critical(msg)
                return CLIStatus.ERROR
        if args.check:
            if check_status == 0:
                print("Checks: OK")
            else:
                print("Checks: FAILED")
            # Stop here
            return check_status
        print("Archiving settings:")
        print("-- destination : %s" % dest_dir)
        if volume_size:
            print("-- multi-volume: yes")
            print("-- volume size : %s" % volume_size)
        else:
            print("-- multi-volume: no")
        print("-- compression : %s" % args.compresslevel)
        print("-- group       : %s" % ('<default>' if not args.group
                                       else args.group))
        print("Making archive from %s..." % d)
        try:
            a = d.make_archive(out_dir=args.out_dir,
                               volume_size=volume_size,
                               compresslevel=args.compresslevel)
        except Exception as ex:
            logger.critical("exception creating archive: %s" % ex)
            return CLIStatus.ERROR
        archive_size = a.size
        if args.group:
            print("Setting group to '%s'..." % args.group)
            a.chown(group=args.group)
        print("Created archive: %s (%s) [%.1f%%]" %
              (a,
               format_size(archive_size,human_readable=True),
               float(archive_size)/float(size)*100.0
               if size > 0.0 else 100))
        return CLIStatus.OK

    # 'Verify' subcommand
    if args.subcommand == 'verify':
        a = get_rundir_instance(args.archive)
        if not isinstance(a, ArchiveDirectory) and \
           not isinstance(a, CopyArchiveDirectory):
            logger.critical(f"{a.path}: not an archive directory")
            return CLIStatus.ERROR
        print("Verifying %s" % a)
        if a.verify_archive():
            print("-- ok")
            return CLIStatus.OK
        else:
            print("-- failed")
            return CLIStatus.ERROR

    # 'Unpack' subcommand
    if args.subcommand == 'unpack':
        a = ArchiveDirectory(args.archive)
        print("Unpacking archive: %s" % a)
        dest_dir = args.out_dir
        if not dest_dir:
            dest_dir = os.getcwd()
        print("Destination      : %s" % dest_dir)
        if "source_has_symlinks" in a.archive_metadata:
            if a.archive_metadata["source_has_symlinks"]:
                # Check if symlink creation is possible
                if not check_make_symlink(dest_dir):
                    logger.critical("archive includes symlinks but cannot "
                                    "make links under destination directory")
                    return CLIStatus.ERROR
        if "source_has_case_sensitive_filenames" in a.archive_metadata:
            if a.archive_metadata["source_has_case_sensitive_filenames"]:
                # Check if case-sensitive filenames are supported
                if not check_case_sensitive_filenames(dest_dir):
                    logger.critical("archive includes case-sensitive file "
                                    "names but destination cannot handle "
                                    "names which only differ by case")
                    return CLIStatus.ERROR
        d = a.unpack(extract_dir=dest_dir,
                     set_permissions=args.copy_permissions)
        print("Unpacked directory: %s" % d)
        return CLIStatus.OK

    # 'Compare' subcommand
    if args.subcommand == 'compare':
        try:
            d1 = get_rundir_instance(args.dir1)
        except Exception as ex:
            logger.error(ex)
            return CLIStatus.ERROR
        print("Comparing %s against %s" % (d1,args.dir2))
        if d1.verify_copy(args.dir2):
            print("-- ok")
            return CLIStatus.OK
        else:
            print("-- failed")
            return CLIStatus.ERROR

    # 'Search' subcommand
    if args.subcommand == 'search':
        include_archive_name = len(args.archives) > 1
        for archive_dir in args.archives:
            a = ArchiveDirectory(archive_dir)
            for f in a.search(name=args.name,
                              path=args.path,
                              case_insensitive=args.case_insensitive):
                if include_archive_name:
                    print("%s:%s" % (d.path,f.path))
                else:
                    print(f.path)
        return CLIStatus.OK

    # 'Extract' subcommand
    if args.subcommand == 'extract':
        a = ArchiveDirectory(args.archive)
        a.extract_files(args.name,
                        extract_dir=args.out_dir,
                        include_path=args.keep_path)
        return CLIStatus.OK

    # 'Copy' subcommand
    if args.subcommand == "copy":
        try:
            d = get_rundir_instance(args.dir)
        except Exception as ex:
            logger.error(ex)
            return CLIStatus.ERROR
        if isinstance(d, ArchiveDirectory) or \
           isinstance(d, CopyArchiveDirectory):
            logger.critical(f"{d.path}: can't make copy archive from an "
                            "existing archive directory")
            return CLIStatus.ERROR
        dest_dir = args.dest_dir
        if not dest_dir:
            dest_dir = os.getcwd()
        dest_dir = os.path.join(dest_dir, d.basename)
        print(f"Copying to {dest_dir}")
        size = d.size
        check_status = 0
        print(f"Checking {d}...")
        print(f"-- type: {d.__class__.__name__}")
        print(f"-- size: {format_size(size, human_readable=True)}")
        is_readable = d.is_readable
        print(f"-- unreadable files     : {format_bool(not is_readable)}")
        has_symlinks = d.has_symlinks
        print(f"-- symlinks             : {format_bool(has_symlinks)}")
        has_dirlinks = d.has_dirlinks
        print(f"-- dirlinks             : {format_bool(has_dirlinks)}")
        has_external_symlinks = d.has_external_symlinks
        print(f"-- external symlinks    : {format_bool(has_external_symlinks)}")
        has_broken_symlinks = d.has_broken_symlinks
        print(f"-- broken symlinks      : {format_bool(has_broken_symlinks)}")
        has_unresolvable_symlinks = d.has_unresolvable_symlinks
        print(f"-- unresolvable symlinks: {format_bool(has_unresolvable_symlinks)}")
        has_unknown_uids = d.has_unknown_uids
        print(f"-- unknown UIDs         : {format_bool(has_unknown_uids)}")
        has_hard_linked_files = d.has_hard_linked_files
        print(f"-- hard linked files    : {format_bool(has_hard_linked_files)}")
        has_case_sensitive_filenames = d.has_case_sensitive_filenames
        print(f"-- case-sensitive files : {format_bool(has_case_sensitive_filenames)}")
        # Messaging for warnings and errors
        info_msgs = []
        error_msgs = []
        unrecoverable_errors = []
        if not is_readable:
            unrecoverable_errors.append("Unreadable files and/or "
                                        "directories detected")
            check_status = 1
        if has_symlinks:
            needs_symlink_creation = \
                    (len(list(d.symlinks)) > len(list(d.dirlinks)) and
                     not args.replace_symlinks) or \
                    (has_dirlinks and not args.follow_dirlinks) or \
                    (has_broken_symlinks and not args.transform_broken_symlinks)
            if needs_symlink_creation:
                # Test if the target allows us to make symlinks
                parent_dest_dir = os.path.dirname(dest_dir)
                try:
                    if not check_make_symlink(parent_dest_dir):
                        unrecoverable_errors.append("Cannot make symlinks "
                                                    "under destination "
                                                    "directory")
                        check_status = 1
                except Exception as ex:
                    unrecoverable_errors.append("Unable to check if symlinks "
                                                "can be made under destination "
                                                f"directory ({ex})")
                    check_status = 1
        if has_unknown_uids:
            msg = "Unknown UID(s) detected"
            if args.force:
                info_msgs.append(f"{msg} (ignored)")
            else:
                error_msgs.append(msg)
                check_status = 1
        if has_dirlinks:
            if args.follow_dirlinks:
                info_msgs.append("Dirlinks detected (ignored; symlinks "
                                 "to directories will be converted to "
                                 "directories and the contents copied "
                                 "recursively)")
            elif args.replace_symlinks:
                unrecoverable_errors.append("Dirlinks detected but "
                                            "--replace-symlinks was "
                                            "specified (add "
                                            "--follow-dirlinks to fix)")
                check_status = 1
            else:
                pass
        if has_external_symlinks:
            if args.replace_symlinks:
                info_msgs.append("External symlinks detected (ignored; "
                                 "will be replaced by link targets)")
            else:
                msg = "External symlinks detected"
                if args.force:
                    info_msgs.append(f"{msg} (ignored; external links "
                                     "will be copied as-is)")
                else:
                    error_msgs.append(msg)
                    check_status = 1
        if has_broken_symlinks or has_unresolvable_symlinks:
            if args.transform_broken_symlinks:
                info_msgs.append("Broken and/or unresolvable symlinks "
                                 "detected (ignored; will be replaced by "
                                 "placeholder files)")
            elif args.replace_symlinks:
                unrecoverable_errors.append("Broken and/or unresolvable "
                                            "symlinks detected but "
                                            "--replace-symlinks was "
                                            "specified (add "
                                            "--transform-broken-symlinks "
                                            "to fix)")
                check_status = 1
            else:
                msg = "Broken and/or unresolvable symlinks detected"
                if args.force:
                    info_msgs.append(f"{msg} (ignored; broken/unresolvable "
                                     "links will be copied as-is)")
                else:
                    error_msgs.append(msg)
                    check_status = 1
        if has_hard_linked_files:
            msg = "Hard-linked files detected"
            if args.force:
                info_msgs.append(f"{msg} (ignored; hard-linked files may "
                                 "appear as multiple copies)")
            else:
                error_msgs.append(msg)
                check_status = 1
        if has_case_sensitive_filenames:
            # Test if the target distinguishes filenames
            # which only differ by case
            parent_dest_dir = os.path.dirname(dest_dir)
            try:
                if not check_case_sensitive_filenames(parent_dest_dir):
                    unrecoverable_errors.append("Destination directory "
                                                "is case-insensitive "
                                                "file system; cannot "
                                                "handle file names which "
                                                "only differ by case")
                    check_status = 1
            except Exception as ex:
                unrecoverable_errors.append("Unable to check if destination "
                                            "directory is on case-insensitive "
                                            f"file system ({ex})")
                check_status = 1
        if os.path.exists(dest_dir):
            unrecoverable_errors.append(
                f"{dest_dir}: destination directory already exists")
            check_status = 1
        # Handle warnings and errors
        for msg in info_msgs:
            print(f"INFO: {msg}")
        for msg in error_msgs:
            if args.check or args.force:
                logger.warning(msg)
            else:
                logger.critical(msg)
        for msg in unrecoverable_errors:
            logger.critical(msg)
        if args.check:
            if check_status == 0:
                print("Checks: OK")
            else:
                print("Checks: FAILED")
            # Stop here
            return check_status
        if unrecoverable_errors or (error_msgs and not args.force):
            return CLIStatus.ERROR
        print(f"Copying contents of {d} to {dest_dir}")
        try:
            dcopy = d.copy(
                dest_dir,
                replace_symlinks=args.replace_symlinks,
                follow_dirlinks=args.follow_dirlinks,
                transform_broken_symlinks=args.transform_broken_symlinks)
        except Exception as ex:
            logger.critical(f"exception creating copy: {ex}")
            return CLIStatus.ERROR
        archive_size = dcopy.size
        print(f"Created copy: {dcopy} "
              f"({format_size(archive_size,human_readable=True)})")
        return CLIStatus.OK

    # No command
    logger.critical("No command supplied (use -h to see options)")
    return CLIStatus.ERROR
