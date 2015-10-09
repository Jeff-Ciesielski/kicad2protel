#! /usr/bin/env python

# kicad2protel: kicad gerber output normalizer
# Copyright (C) 2015 Jeff Ciesielski <jeffceisielski@gmail.com>
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
import os
import sys
import shutil
import copy
import argparse
import logging
import operator
import zipfile

logging.debug("")
_log = logging.getLogger('kicad2protel')
_log.setLevel(logging.INFO)


# NOTE: All excellon info gleaned from :
# http://web.archive.org/web/20071030075236/http://www.excellon.com/manuals/program.htm

gerber_extension_map = {
    '-F_SilkS.gbr': '.GTO',
    '-F_Mask.gbr': '.GTS',
    '-F_Cu.gbr': '.GTL',
    '-B_Cu.gbr': '.GBL',
    '-B_Mask.gbr': '.GBS',
    '-B_SilkS.gbr': '.GBO',
    '-Edge_Cuts.gbr': '.GML',
    '-In1_Cu.gbr': '.G1',
    '-In2_Cu.gbr': '.G2',
    
    '-F_SilkS.gto': '.GTO',
    '-F_Mask.gts': '.GTS',
    '-F_Cu.gtl': '.GTL',
    '-B_Cu.gbl': '.GBL',
    '-B_Mask.gbs': '.GBS',
    '-B_SilkS.gbo': '.GBO',
    '-Edge_Cuts.gml': '.GML',
    '-In1_Cu.g2': '.G1',
    '-In2_Cu.g3': '.G2',
}

class IncompatibleInstructionException(Exception):
    pass

class ExcellonHeader(object):
    def __init__(self, header_lines):
        self.tools = {}
        self._process(header_lines)

    def _process(self, lines):
        _handler_map = {
            'T': self._handle_tool,
            'INCH': self._handle_measurement,
            'METRIC': self._handle_measurement
        }
        for line in lines:
            for pos in range(len(line)):
                if line[:pos] in _handler_map:
                    _handler_map[line[:pos]](line)
                    break

    def _handle_tool(self, line):
        t = ExcellonTool(line)
        self.tools[t.tool_id] = t

    def _handle_measurement(self, line):
        self.meas_mode, self.zero_style = line.strip().split(',')

    def dumps(self):
        return '\n'.join([
            'M48',
            '{},{}'.format(self.meas_mode, self.zero_style),
            '\n'.join([x.dumps() for x in self.tool_list]),
            '%'
        ])

    def __str__(self):

        return '\n'.join([
            20*'-',
            'Excellon Header',
            'Measurement Mode:{}'.format(self.meas_mode),
            'Zero Style: {}'.format(self.zero_style),
            'Tools:',
            '  -{}'.format('\n  -'.join(['{}:{}'.format(x.tool_id, x.diameter)
                                         for x in self.tool_list])),
            ''
        ])

    @property
    def tool_list(self):
        return [self.tools[x] for x in sorted(self.tools)]

    def optimize(self):
        drill_map = {}

        for t in self.tool_list:
            if not t.diameter in drill_map:
                drill_map[t.diameter] = []
            drill_map[t.diameter].append(t)

        tool_remap = {}
        new_tools = {}
        for idx, d in enumerate(sorted(drill_map)):
            tool_id = 'T{}'.format(idx + 1)
            new_tools[tool_id] = copy.deepcopy(drill_map[d][0])
            new_tools[tool_id].tool_id = tool_id
            for tool in drill_map[d]:
                tool_remap[tool.tool_id] = tool_id

        self.tools = new_tools
        return tool_remap

    def __add__(self, other):
        if not isinstance(other, ExcellonHeader):
            raise ValueError('Cannot add ExcellonHeader and {}'.format(type(other)))

        # TODO: Not sure how to handle this for now, bail out
        if not self.meas_mode == other.meas_mode:
            raise IncompatibleInstructionException(
                '\n'.join([
                    'Cannot merge due to differing measurement modes:',
                    '  F1: {}'.format(self.meas_mode),
                    '  F2: {}'.format(other.meas_mode)
                ])
            )

        # Create a working copy of self
        wh = copy.deepcopy(self)

        # Move over and rename all tools from the 'other' instance
        for t in sorted(other.tools):
            t_copy = copy.deepcopy(other.tools[t])
            t_idx = 'T{}'.format(len(wh.tools) + 1)
            t_copy.tool_id = t_idx
            wh.tools[t_idx] = t_copy

        return wh

class ExcellonTool(object):
    def __init__(self, tooldefstr):
        diam_idx = tooldefstr.index('C')
        self.tool_id = tooldefstr[:diam_idx]
        self.diameter = tooldefstr[diam_idx + 1:]

    def __eq__(self, other):
        return self.diameter == other.diameter

    def __hash__(self):
        return hash(self.diameter)

    def __lt__(self, other):
        return float(self.diameter) < float(other.diameter)


    def dumps(self):
        return '{}C{}'.format(self.tool_id, self.diameter)

class InvalidToolException(Exception):
    pass

class InvalidToolpathException(Exception):
    pass

class ExcellonDrillInstr(object):
    def __init__(self, filepath):
        self._lines = [x.strip() for x in open(filepath).readlines() if len(x.strip())]
        self._toolpaths = {}
        self._current_tool = None

        sidx, eidx = self._get_header_bounds()
        self.header = ExcellonHeader(self._lines[sidx:eidx])

        for tool in self.header.tools:
            self._toolpaths[tool] = []

        sidx, eidx = self._get_body_bounds()

        self._process(self._lines[sidx:eidx])

    def _get_header_bounds(self):
        return self._lines.index('M48') + 1, self._lines.index('%')

    def _get_body_bounds(self):
        return self._lines.index('%') + 1, self._lines.index('M30')

    def _handle_tool(self, line):
        tool = line.strip()
        if tool not in self.header.tools and not tool == 'T0':
            raise InvalidToolException('Unknown tool: {}'.format(tool))
        self._current_tool = tool

    def _handle_coord(self, line):
        if not self._current_tool:
            raise InvalidToolpathException('No Tool selected')

        self._toolpaths[self._current_tool].append(line.strip())

    def _process(self, lines):
        _handler_map = {
            'T': self._handle_tool,
            'X': self._handle_coord,
        }

        self._current_tool = None
        for line in lines:
            for pos in range(len(line)):
                if line[:pos] in _handler_map:
                    _handler_map[line[:pos]](line)
                    break

    def _dumps_toolpaths(self):
        rs = ''
        for t in sorted(self._toolpaths):
            rs += '\n{}\n'.format(t)
            rs += '\n'.join(self._toolpaths[t])

        # Return the slice to strip off the leading newline
        return rs[1:]

    def dumps(self):
        _meas_mode_map = {
            'INCH':'M72',
            'METRIC':'M71',
        }
        return '\n'.join([
            self.header.dumps(),
            'G90', #absolute mode
            'G05', #drill mode
            _meas_mode_map[self.header.meas_mode], # Metric or Inch mode
            self._dumps_toolpaths(),
            'T0',
            'M30',
        ])

    def __add__(self, other):
        if not isinstance(other, ExcellonDrillInstr):
            raise ValueError('Cannot add ExcellonDrillInstr and {}'.format(type(other)))

        # Create a working instruction set
        wi = copy.deepcopy(self)

        # First, Add the toolpaths together, renumbering starting from
        # the end of our tool numbering
        tp_len = len(self._toolpaths)
        for idx, tp_id in enumerate(sorted(other._toolpaths)):
            tp_idx = tp_len + idx + 1
            new_tp_id = 'T{}'.format(tp_idx)
            wi._toolpaths[new_tp_id] = other._toolpaths[tp_id][:]

        # Now, combine the headers
        wi.header += other.header

        # Optimize the header and get the new mapping
        tool_remap = wi.header.optimize()

        # Now, remap our toolpath
        new_toolpaths = {}
        for tp in sorted(wi._toolpaths):
            if not tool_remap[tp] in new_toolpaths:
                new_toolpaths[tool_remap[tp]] = wi._toolpaths[tp][:]
            else:
                new_toolpaths[tool_remap[tp]].extend(wi._toolpaths[tp][:])
        wi._toolpaths = new_toolpaths
        return wi

# http://stackoverflow.com/questions/1855095/how-to-create-a-zip-archive-of-a-directory
def zipdir(path, ziph):
    # ziph is zipfile handle
    for root, dirs, files in os.walk(path):
        for file in files:
            ziph.write(os.path.join(root, file))

if __name__ == '__main__':
    main()

def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--in_dir', '-i',
                            help='Directory containing KiCad plot output',
                            required=True)
    arg_parser.add_argument('--out_dir', '-o',
                            help='Directory to store newly created files. '
                            '(Will be created automatically if nonexistant)',
                            required=True)
    arg_parser.add_argument('--zip', '-z', help="Create zip archive of new files", default=False, action='store_true')
    args = arg_parser.parse_args()

    if not os.path.isdir(args.out_dir):
        os.makedirs(args.out_dir)


    drill_files = {}
    for filename in os.listdir(args.in_dir):
        print "Testing:", filename
        for ext in gerber_extension_map:
            if filename[-len(ext):] == ext:
                new_name =  filename[:-len(ext)] + gerber_extension_map[ext]
                shutil.copy(os.path.join(args.in_dir, filename), os.path.join(args.out_dir, new_name))
                _log.info('{} converted to: {}'.format(filename, new_name))

        if filename[-4:] == '.drl':
            if '-NPTH.drl' in filename:
                ext = '-NPTH.drl'
            else:
                ext = '.drl'
            _log.info('Processing Excellon File: {}'.format(filename))
            base_name =  filename[:-len(ext)]
            di = ExcellonDrillInstr(os.path.join(args.in_dir, filename))
            if not base_name in drill_files:
                drill_files[base_name] = []
            drill_files[base_name].append(di)

    # For each drill file in the project, create a combined optimized
    # version and dump it in the new directory
    for dfile, excellon_objs in drill_files.items():
        output_file = os.path.join(args.out_dir, '{}.txt'.format(dfile))

        cmb_exc = reduce(operator.add, excellon_objs)
        with open(output_file, 'w') as fhandle:
            fhandle.write(cmb_exc.dumps())

    if args.zip:
        with zipfile.ZipFile('{}.zip'.format(args.out_dir), 'w') as zf:
            zipdir(args.out_dir, zf)

        shutil.rmtree(args.out_dir)
        
