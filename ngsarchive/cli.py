#!/usr/bin/env python3
#
#     cli.py: command line interface classes and functions
#     Copyright (C) University of Manchester 2023 Peter Briggs
#

"""
"""

#######################################################################
# Imports
#######################################################################

import logging
from argparse import ArgumentParser
from .archive import ArchiveDirectory
from .archive import convert_size_to_bytes
from .archive import format_size
from .archive import get_rundir_instance

#######################################################################
# Logger
#######################################################################

logger = logging.getLogger(__name__)
logging.basicConfig(level="INFO",format='%(levelname)s: %(message)s')

#######################################################################
# Functions
#######################################################################

def main():
    """
    """
    # Top-level parser
    p = ArgumentParser(description="NGS data archiving utility")

    # Subcommands
    s = p.add_subparsers(dest='subcommand')

    # 'info' command
    parser_info = s.add_parser('info',
                               help="Get information on a directory")
    parser_info.add_argument('dir',
                             help="path to directory")
    parser_info.add_argument('--list',action='store_true',
                             help="list unreadable files, external "
                             "symlinks etc")

    # 'archive' command
    parser_archive = s.add_parser('archive',
                                  help="Make archive of a directory")
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
    parser_archive.add_argument('--force',action='store_true',
                                help="ignore problems about unreadable "
                                "files and external symlinks")

    # 'verify' command
    parser_verify = s.add_parser('verify',
                                  help="Verify an archive directory")
    parser_verify.add_argument('archive',
                               help="path to archive directory")

    # 'unpack' command
    parser_unpack = s.add_parser('unpack',
                                  help="Unpack (extract) an archive")
    parser_unpack.add_argument('archive',
                               help="path to archive directory")
    parser_unpack.add_argument('-o','--out-dir',metavar='OUT_DIR',
                               action='store',dest='out_dir',
                               help="unpack archive under OUT_DIR "
                               "(default: current directory)")

    # 'verify_copy' command
    parser_verify_copy = s.add_parser('verify_copy',
                                      help="check one directory against "
                                      "another")
    parser_verify_copy.add_argument('dir1',
                                    help="path to first directory")
    parser_verify_copy.add_argument('dir2',
                                    help="path to second directory")

    # 'search' command
    parser_search = s.add_parser('search',
                                 help="search within one or more archives")
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

    # 'extract_files' command
    parser_extract_files = s.add_parser('extract_files',
                                        help="extract specific files from an "
                                        "archive")
    parser_extract_files.add_argument('archive',
                                      help="path to archive directory")
    parser_extract_files.add_argument('-name',action='store',
                                      help="name or pattern to match base "
                                      "of file names to be extracted")
    parser_extract_files.add_argument('-o','--out-dir',metavar='OUT_DIR',
                                      action='store',dest='out_dir',
                                      help="extract files into OUT_DIR "
                                      "(default: current directory)")
    parser_extract_files.add_argument('-k','--keep-path',
                                      action='store_true',
                                      help="preserve the leading directory "
                                      "paths when extracting files (default "
                                      "is to drop leading paths)")

    # Parse the arguments
    args = p.parse_args()
    
    # 'Info' subcommand
    if args.subcommand == "info":
        d = get_rundir_instance(args.dir)
        size = d.size
        print("Path: %s" % d.path)
        print("Type: %s" % d.__class__.__name__)
        print("Size: %s" % format_size(size,human_readable=True))
        compressed_file_size = d.getsize(d.compressed_files)
        print("Compressed contents: %s [%.1f%%]" %
              (format_size(compressed_file_size,human_readable=True),
              float(compressed_file_size)/float(size)*100.0))
        if args.list:
            print("Unreadable files:")
            is_readable = True
            for f in d.unreadable_files:
                print("-- %s" % f)
                is_readable = False
            if is_readable:
                print("-- no unreadable files")
            print("External symlinks:")
            has_external_symlinks = False
            for s in d.external_symlinks:
                print("-- %s" % s)
                has_external_symlinks = True
            if not has_external_symlinks:
                print("-- no external symlinks")
            print("Hard linked files:")
            has_hard_links = False
            for f in d.hard_linked_files:
                print("-- %s" % f)
                has_hard_links = True
            if not has_hard_linked_files:
                print("-- no hard linked files")
            has_unknown_uids = False
            for f in d.unknown_uids:
                print("-- %s" % f)
                has_unknown_uids = True
            if not has_unknown_uids:
                print("-- no files with unknown UIDs")
        else:
            print("Unreadable files : %s" % (not d.is_readable))
            print("External symlinks: %s" % d.has_external_symlinks)
            print("Hard linked files: %s" % d.has_hard_linked_files)
            print("Unknown UIDs     : %s" % d.has_unknown_uids)

    # 'Archive' subcommand
    if args.subcommand == "archive":
        d = get_rundir_instance(args.dir)
        size = d.size
        print("Checking %s..." % d)
        print("-- type          : %s" % d.__class__.__name__)
        print("-- size          : %s" % format_size(size,
                                                    human_readable=True))
        is_readable = d.is_readable
        print("-- unreadable files : %s" % (not is_readable))
        has_external_symlinks = d.has_external_symlinks
        print("-- external symlinks: %s" % has_external_symlinks)
        has_unknown_uids = d.has_unknown_uids
        print("-- unknown UIDs     : %s" % has_unknown_uids)
        has_hard_linked_files = d.has_hard_linked_files
        print("-- hard linked files: %s" % has_hard_linked_files)
        if has_external_symlinks or \
           not is_readable or \
           has_unknown_uids:
            msg = "Readability, symlink and/or UID issues detected"
            if args.force:
                logger.warning("%s (ignored)" % msg)
            else:
                logger.critical(msg)
                return 1
        if has_hard_linked_files and args.volume_size:
            msg = "Hard links detected with multi-volume archiving"
            if args.force:
                logger.warning("%s (ignored)" % msg)
            else:
                logger.critical(msg)
                return 1
        volume_size = args.volume_size
        if volume_size and convert_size_to_bytes(volume_size) > size:
            logger.warning("volume size larger than uncompressed "
                           "size, disabling multi-volume archive")
            volume_size = None
        print("Archiving settings:")
        print("-- destination : %s" % ('CWD' if not args.out_dir
                                       else args.out_dir))
        if volume_size:
            print("-- multi-volume: yes")
            print("-- volume size : %s" % volume_size)
        else:
            print("-- multi-volume: no")
        print("-- compression : %s" % args.compresslevel)
        print("Archiving %s..." % d)
        a = d.make_archive(out_dir=args.out_dir,
                           volume_size=volume_size,
                           compresslevel=args.compresslevel)
        archive_size = a.size
        print("Created archive: %s (%s) [%.1f%%]" %
              (a,
               format_size(archive_size,human_readable=True),
               float(archive_size)/float(size)*100.0))

    # 'Verify' subcommand
    if args.subcommand == 'verify':
        a = ArchiveDirectory(args.archive)
        print("Verifying %s" % a)
        if a.verify_archive():
            print("-- ok")
            return 0
        else:
            print("-- failed")
            return 1

    # 'Unpack' subcommand
    if args.subcommand == 'unpack':
        a = ArchiveDirectory(args.archive)
        print("Unpacking archive: %s" % a)
        print("Destination      : %s" % ('CWD' if not args.out_dir
                                         else args.out_dir))
        d = a.unpack(extract_dir=args.out_dir)
        print("Unpacked directory: %s" % d)

    # 'Verify_copy' subcommand
    if args.subcommand == 'verify_copy':
        d1 = get_rundir_instance(args.dir1)
        print("Verifying %s against %s" % (d1,args.dir2))
        if d1.verify_copy(args.dir2):
            print("-- ok")
            return 0
        else:
            print("-- failed")
            return 1

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

    # 'Extract_files' subcommand
    if args.subcommand == 'extract_files':
        a = ArchiveDirectory(args.archive)
        a.extract_files(args.name,
                        extract_dir=args.out_dir,
                        include_path=args.keep_path)
