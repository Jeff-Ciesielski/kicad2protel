import os
from setuptools import setup
import glob
# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name = "kicad2protel",
    version = "1.0.0",
    author = "Jeff Ciesielski",
    author_email = "jeffciesielski@gmail.com",
    description = ("Kicad output normalizer"),
    license = "GPLv2",
    packages=['kicad2protel'],
    package_dir={'kicad2protel': '.'},
    keywords = "PCB manufacturing",
    url = "https://github.com/Jeff-Ciesielski/kicad2protel",
    long_description=read('README.md'),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Topic :: Utilities",
        "License :: OSI Approved :: GPLv2 License",
    ],
    entry_points={
        "console_scripts": [
            'kicad2protel = kicad2protel:main'
    ]},
)
