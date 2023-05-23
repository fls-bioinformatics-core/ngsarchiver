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

    # 'verify_copy' command
    parser_verify_copy = s.add_parser('verify_copy',
                                      help="check one directory against "
                                      "another")
    parser_verify_copy.add_argument('dir1',
                                    help="path to first directory")
    parser_verify_copy.add_argument('dir2',
                                    help="path to second directory")

    # Parse the arguments
    args = p.parse_args()
    
    # 'Info' subcommand
    if args.subcommand == "info":
        d = get_rundir_instance(args.dir)
        print("Path: %s" % d.path)
        print("Type: %s" % d.__class__.__name__)
        print("Size: %s" % format_size(d.size,human_readable=True))
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
        else:
            print("Readable : %s" % d.is_readable)
            print("External symlinks: %s" % d.has_external_symlinks)

    # 'Archive' subcommand
    if args.subcommand == "archive":
        d = get_rundir_instance(args.dir)
        print("Checking %s..." % d)
        print("-- type          : %s" % d.__class__.__name__)
        print("-- size          : %s" % format_size(d.size,
                                                    human_readable=True))
        is_readable = d.is_readable
        print("-- readable      : %s" % is_readable)
        has_external_symlinks = d.has_external_symlinks
        print("-- external links: %s" % has_external_symlinks)
        if has_external_symlinks or not is_readable:
            if args.force:
                logger.warning("readability and/or symlink issues (ignored)")
            else:
                logger.critical("readability and/or symlink issues")
                return 1
        print("Archiving %s..." % d)
        a = d.make_archive('gztar')
        print("Archive file: %s (%s)" % (a,format_size(a.size,
                                                       human_readable=True)))

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
        print("Unpacking %s" % a)
        d = a.unpack()
        print("Directory: %s" % d)
        return 1

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
