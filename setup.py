#!/usr/bin/env python

from setuptools import setup

setup(
    name="bravo.plugin",
    version="1.9",
    url="http://github.com/MostAwesomeDude/bravo.plugin",
    license="MIT",
    author="Corbin Simpson",
    author_email="cds@corbinsimpson.com",
    description="Featureful interface-based plugin loader",
    long_description=open("README.rst").read(),
    packages=["exocet"],
    py_modules=["bravo_plugin"],
    platforms="any",
    install_requires=["zope.interface"],
    classifiers=[
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
    ],
)
