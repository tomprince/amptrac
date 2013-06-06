# This file is part of txgithub.  txgithub is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from distutils.core import setup
import setuptools

setup(
    name='amptrac',
    version='0.0',
    url='https://github.com/tomprince/amptrac',
    description="Client for twisted's amp interface to trac",
    license='MIT',
    author='Tom Prince',
    author_email='tom.prince@ualberta.net',
    packages=['amptrac', 'amptrac.scripts', 'amptrac.test'],
    scripts=['bin/fetch-ticket', 'bin/review-tickets', 'bin/get-attachment'],
    install_requires=[
        'twisted >= 13.0.0',
        'treq',
    ],
    zip_safe=False,
)
