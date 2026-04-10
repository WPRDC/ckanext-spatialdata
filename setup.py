#!/usr/bin/env python
# encoding: utf-8


from setuptools import find_packages, setup

__version__ = u'1.0.0-alpha'

with open(u'README.md', u'r') as f:
    __long_description__ = f.read()

setup(
    name=u'ckanext-spatialdata',
    version=__version__,
    description=u'A CKAN extension that provides geospatial awareness of datastore data.',
    long_description=__long_description__,
    classifiers=[
        u'Development Status :: 3 - Alpha',
        u'Framework :: Flask',
        u'Programming Language :: Python :: 2.7'
    ],
    keywords=u'CKAN data spatialdata',
    author=u'Steve Saylor',
    author_email=u'steven.saylor@pitt.edu',
    url=u'https://github.com/wprdc/ckanext-spatialdata',
    license=u'AGPLv3',
    packages=find_packages(exclude=[u'tests']),
    namespace_packages=[u'ckanext', u'ckanext.spatialdata'],
    include_package_data=True,
    zip_safe=False,
    install_requires=[],
    entry_points= \
        u'''
        [ckan.plugins]
            spatialdata=ckanext.spatialdata.plugin:spatialdataPlugin

        [paste.paster_command]
            spatialdata=ckanext.spatialdata.commands.spatialdata:spatialdataCommand
        ''',
    )
