#!/usr/bin/python
# vim:fileencoding=utf-8:noet
# (C) 2017 Michał Górny <mgorny@gentoo.org>
# Released under the terms of the 2-clause BSD license.

from distutils.core import setup

import os.path
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
try:
	from flaggie import PV
except ImportError:
	PV = 'unknown'

setup(
	name='flaggie',
	version=PV,
	author='Michał Górny',
	author_email='mgorny@gentoo.org',
	url='http://github.com/mgorny/flaggie',

	package_dir={'': 'lib'},
	packages=['flaggie'],
	scripts=['flaggie'],

	classifiers=[
		'Development Status :: 4 - Beta',
		'Environment :: Console',
		'Intended Audience :: System Administrators',
		'License :: OSI Approved :: BSD License',
		'Operating System :: POSIX',
		'Programming Language :: Python',
		'Topic :: System :: Installation/Setup'
	]
)
