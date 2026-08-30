#!/usr/bin/env python
from setuptools import find_packages, setup

__version__ = '1.0.0-alpha'

with open('README.md', 'r') as f:
    __long_description__ = f.read()

setup(
    name='ckanext-spatialdata',
    version=__version__,
    description='A CKAN extension that provides geospatial awareness of datastore data.',
    long_description=__long_description__,
    long_description_content_type='text/markdown',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Framework :: Flask',
        'Programming Language :: Python :: 3',
    ],
    keywords='CKAN data spatialdata',
    author='Steve Saylor',
    author_email='steven.saylor@pitt.edu',
    url='https://github.com/wprdc/ckanext-spatialdata',
    license='AGPLv3',
    packages=find_packages(exclude=['tests']),
    namespace_packages=['ckanext'],
    include_package_data=True,
    zip_safe=False,
    install_requires=[],
    entry_points='''
        [ckan.plugins]
        spatialdata=ckanext.spatialdata.plugin:SpatialdataPlugin
    ''',
)
