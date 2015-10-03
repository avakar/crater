#!/usr/bin/env python
# coding: utf-8

from setuptools import setup

setup(
    name='crater',
    version='0.1.4',

    description='A dependency management system',
    author='Martin Vejnár',
    author_email='avakar@ratatanek.cz',
    url='https://github.com/avakar/crater',
    license='MIT',

    packages=['crater'],
    install_requires=['pytoml'],
    entry_points = {
        'console_scripts': [
            'crater = crater.crater:main',
            ]
        }
    )
