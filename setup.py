"""Description

Setup script to install ngsarchive

Copyright (C) University of Manchester 2023 Peter Briggs

"""

# Hack to acquire all scripts that we want to
# install into 'bin'
from glob import glob
scripts = []
for pattern in ('bin/*.py',):
    scripts.extend(glob(pattern))

# Installation requirements
install_requires = ['genomics-bcftbx',
                    'auto-process-ngs']

# Setup for installation etc
from setuptools import setup
import ngsarchive
setup(name = "ngsarchive",
      version = ngsarchive.get_version(),
      description = 'Utility to manage BCF NGS data archive',
      long_description = """Utilities to archive, interrogate and recover NGS data held by the BCF from Illumina and SOLiD platforms""",
      url = 'https://github.com/fls-bioinformatics-core/ngsarchive',
      maintainer = 'Peter Briggs',
      maintainer_email = 'peter.briggs@manchester.ac.uk',
      packages = ['ngsarchive',],
      license = 'AFL-3',
      # Pull in dependencies
      install_requires = install_requires,
      # Enable 'python setup.py test'
      test_suite='nose.collector',
      tests_require=['nose'],
      # Scripts
      scripts = scripts,
      classifiers=[
          "Development Status :: 4 - Beta",
          "Environment :: Console",
          "Intended Audience :: End Users/Desktop",
          "Intended Audience :: Science/Research",
          "Intended Audience :: Developers",
          "License :: OSI Approved :: Academic Free License (AFL)",
          "Operating System :: POSIX :: Linux",
          "Operating System :: MacOS",
          "Topic :: Scientific/Engineering",
          "Topic :: Scientific/Engineering :: Bio-Informatics",
          "Programming Language :: Python :: 3",
          'Programming Language :: Python :: 3.6',
          'Programming Language :: Python :: 3.7',
          'Programming Language :: Python :: 3.8',
      ],
      include_package_data=True,
      zip_safe = False)
