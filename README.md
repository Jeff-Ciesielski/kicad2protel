# kicad2protel

---

This tool normalizes filename outputs from kicad's plotting output
(both kicad filenames and protel).  In addition, it will combine the
dual excellon drill files and optimize the tool allocation (removing
duplicates)


## Installation

Standard python installation using setuptools

`python setup.py install`


## Use

`kicad2protel -i <input_dir> -o <output_dir> (-z optional)`

Passing the -z option will output a zip file instead of a folder
