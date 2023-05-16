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

from argparse import ArgumentParser
from .archive import ArchiveDirectory
from .archive import format_size
from .archive import get_rundir_instance

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

    # 'archive' command
    parser_archive = s.add_parser('archive',
                                  help="Make archive of a directory")
    parser_archive.add_argument('dir',
                                help="path to directory")

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

    # 'Archive' subcommand
    if args.subcommand == "archive":
        d = get_rundir_instance(args.dir)
        print("Archiving %s (%s)" % (d,format_size(d.size,
                                                   human_readable=True)))
        a = d.make_archive('gztar')
        print("Archive file: %s (%s)" % (a,format_size(a.size,
                                                       human_readable=True)))

    # 'Verify' subcommand
    if args.subcommand == 'verify':
        a = ArchiveDirectory(args.archive)
        print("Verifying %s" % a)
        print(a.verify_archive())

    # 'Unpack' subcommand
    if args.subcommand == 'unpack':
        a = ArchiveDirectory(args.archive)
        print("Unpacking %s" % a)
        d = a.unpack()
        print("Directory: %s" % d)

    # 'Verify_copy' subcommand
    if args.subcommand == 'verify_copy':
        d1 = get_rundir_instance(args.dir1)
        print("Verifying %s against %s" % (d1,args.dir2))
        print(d1.verify_copy(args.dir2))

    
