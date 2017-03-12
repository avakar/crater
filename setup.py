#!/usr/bin/env python
# coding: utf-8

from setuptools import setup

setup(
    name='crater',
    version='0.3',

    description='A dependency management system',
    author='Martin Vejnár',
    author_email='vejnar.martin@gmail.com',
    url='https://github.com/avakar/crater',
    license='MIT',

    packages=['crater'],
    install_requires=['cson', 'six', 'requests', 'colorama', 'toposort'],
    entry_points = {
        'console_scripts': [
            'crater = crater.crater:main',
            ]
        }
    )
