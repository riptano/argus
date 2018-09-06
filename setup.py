from os import path

import src
from setuptools import find_packages, setup

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'readme.md')) as f:
    long_description = f.read()

setup(
    name='argus',
    version=src.__version__,
    description='Argus',
    long_description=long_description,
    url='https://github.com/riptano/argus',
    packages=find_packages(),
    scripts=['argus.py'],
    install_requires=[
        'dateutils>=0.6.6',
        'dill>=0.2.7.1',
        'jenkinsapi>=0.3.4',
        'jira>=1.0.10',
        'mock>=2.0.0',
        'mypy>=0.550',
        'nose>=1.3.7',
        'six>=1.4.1',
        'typing>=3.6.2',
        'tzlocal>=1.4'
    ],
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python",
        'Programming Language :: Python :: 3.6.5'
    ]
)
