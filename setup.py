"""Description

Setup script to install ngsarchiver package

Copyright (C) University of Manchester 2023-2025 Peter Briggs

"""

# Hack to acquire all scripts that we want to
# install into 'bin'
from glob import glob
scripts = ['bin/archiver']
for pattern in ('bin/*.py',):
    scripts.extend(glob(pattern))

# Installation requirements
install_requires = []

# Setup for installation etc
from setuptools import setup
import ngsarchiver
setup(name = "ngsarchiver",
      version = ngsarchiver.get_version(),
      description = 'Utility to archive and manage BCF NGS data',
      long_description = """Utilities to archive, interrogate and recover NGS data held by the BCF from Illumina and SOLiD platforms""",
      url = 'https://github.com/fls-bioinformatics-core/ngsarchiver',
      maintainer = 'Peter Briggs',
      maintainer_email = 'peter.briggs@manchester.ac.uk',
      packages = ['ngsarchiver',],
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
          'Programming Language :: Python :: 3.8',
          'Programming Language :: Python :: 3.9',
          'Programming Language :: Python :: 3.10',
          'Programming Language :: Python :: 3.11',
      ],
      include_package_data=True,
      zip_safe = False)
