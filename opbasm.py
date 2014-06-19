#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright © 2014 Kevin Thibedeau

# This file is part of Open Picoblaze Assembler (OPBASM).

# OPBASM is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.

# OPBASM is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public
# License along with OPBASM. If not, see <http://www.gnu.org/licenses/>.

'''Open Picoblaze Assembler

This is a cross-platform assembler for the Picoblaze-3 and 
Picoblaze-6 processors from Xilinx.

USAGE:
Picoblaze-3 mode (default)

  opbasm.py <source file>.psm [-n <module/entity name>]


Picoblaze-6 mode

  opbasm.py -6 <source file>.psm [-n <module/entity name>]


You can use all Picoblaze-6 syntax extensions in Picoblaze-3 code that don't
depend on PB-6 specific instructions.

For Picoblaze-3 you can use the following extensions from Picoblaze-6:
  * Decimal, binary, and character literals (41'd, 01000001'b, "A")
  * Predefined char constants and date/time stamp fields (CR, LF, HT, datestamp_day, etc.)
  * Inverted constants ( ~my_const )
  * Environment variable constants ( constant foo, %my_env_const )
  * INCLUDE, DEFAULT_JUMP, and INST directives
  * Address label constants (my_label'upper  my_label'lower)

For Picoblaze-3 you CANNOT use the following:
  * STRING and TABLE directives
  * Picoblaze-6 instructions (CALL@, COMPARECY, HWBUILD, JUMP@, LOAD&RETURN,
                              OUTPUTK, REGBANK, STAR, TESTCY)

Picoblaze-6 enhancements:
  KCPSM6.exe has the -c switch to limit the size of memory. OPBASM provides -m to do the same
  as well as -s to limit the scratchpad memory size to 64 or 128 bytes.
  MEM format files are output by default. HEX format is activated with -x.

Refer to the file "all_kcpsm6_syntax.psm" distributed with KCPSM6 for a detailed
explanation of the new Picoblaze-6 syntax.
'''


from __future__ import print_function, division

import sys
import os
from optparse import OptionParser
import datetime
import copy
import string

try:
  from opbasm_lib.color import *
except ImportError:
  # Provide dummy functions if the color module isn't found
  def note(t): return t
  def success(t): return t
  def warn(t): return t
  def error(t): return t

try:
  from pyparsing import *
except ImportError:
  print(error('ERROR:') + ' OPBASM requires the Pyparsing library')
  sys.exit(1)


__version__ = '0.9'

ParserElement.setDefaultWhitespaceChars(' \t')

class FatalError(Exception):
  '''General error reporting exception'''
  def __init__(self, statement, *args):
    self.statement = statement
    self.args = args

  def __str__(self):
    return '{}\n{}'.format(self.statment, self.args)


def get_op_info(use_pb6):
  '''Generate a dict of opcode info for each Picoblaze target'''
  op_info = {}

  if not use_pb6:
    op_info['has_string_table_support'] = False

    op_info['opcodes'] = { \
      'add': 0x18000, 'addcy': 0x1a000, 'and': 0x0a000, 'call': 0x30000, \
      'compare': 0x14000, 'disable': 0x3c000, 'enable': 0x3c001,
      'fetch': 0x06000, 'input': 0x04000, 'jump': 0x34000, \
      'load': 0x00000, 'or': 0x0c000, 'output': 0x2c000, 'return': 0x2a000, \
      'returni': 0x38000, \
      'rl': 0x20002, 'rr': 0x2000c, 'sl0': 0x20006, 'sl1': 0x20007, \
      'slx': 0x20004, 'sla': 0x20000, 'sr0': 0x2000e, 'sr1': 0x2000f, \
      'sra': 0x20008, 'srx': 0x2000a, 'store': 0x2e000, 'sub': 0x1c000, \
      'subcy': 0x1e000, 'test': 0x12000, 'xor': 0x0e000, \
      'inst': 0x00000 \
    }

    op_info['flag_opcodes'] = set(('call', 'jump', 'return'))
    op_info['flag_codes'] = {
      'c' : 0x1800,
      'nc': 0x1c00,
      'z' : 0x1000,
      'nz': 0x1400
    }
    op_info['return_flag_codes'] = op_info['flag_codes']

    op_info['addr_opcodes'] = set(('call', 'jump'))

    op_info['one_reg_opcodes'] = set(('rl', 'rr', 'sl0', 'sl1', 'sla', 'slx', 'sr0', 'sr1', 'sra', 'srx'))

    op_info['two_reg_opcodes'] = set(('add', 'addcy', 'and', 'compare', 'fetch', 'input', \
      'load', 'or', 'output', 'store', 'sub', 'subcy', 'test', 'xor'))
    op_info['two_reg_op_offset'] = 0x1000

    op_info['directives'] = set(('address', 'constant', 'namereg', \
        'include', 'default_jump'))

  else: # Picoblaze-6
    op_info['has_string_table_support'] = True

    op_info['opcodes'] = { \
      'add': 0x11000, 'addcy': 0x13000, 'and': 0x03000, 'call': 0x20000, \
      'compare': 0x1d000, 'disable': 0x28000, 'enable': 0x28001,
      'fetch': 0x0b000, 'input': 0x09000, 'jump': 0x22000, \
      'load': 0x01000, 'or': 0x05000, 'output': 0x2d000, 'return': 0x25000, \
      'returni': 0x29000, \
      'rl': 0x14002, 'rr': 0x1400c, 'sl0': 0x14006, 'sl1': 0x14007, \
      'slx': 0x14004, 'sla': 0x14000, 'sr0': 0x1400e, 'sr1': 0x1400f, \
      'sra': 0x14008, 'srx': 0x1400a, 'store': 0x2f000, 'sub': 0x19000, \
      'subcy': 0x1b000, 'test': 0x0d000, 'xor': 0x07000, \

      # New Picoblaze-6 instructions:
      'call@': 0x24000, 'comparecy': 0x1f000, 'hwbuild': 0x14080, 'jump@': 0x26000, \
      'load&return': 0x21000, 'outputk': 0x2b000, 'regbank': 0x37000, 'star': 0x16000, \
      'testcy': 0x0f000, 'inst': 0x00000 \
    }

    op_info['flag_opcodes'] = set(('call', 'jump', 'return'))
    op_info['flag_codes'] = {
      'c' : 0x18000,
      'nc': 0x1c000,
      'z' : 0x10000,
      'nz': 0x14000
    }

    # Picoblaze-6 uses inconsistent offsets for the conditional return instructions
    op_info['return_flag_codes'] = {
      'c' : 0x14000,
      'nc': 0x18000,
      'z' : 0x0c000,
      'nz': 0x10000
    }

    op_info['addr_opcodes'] = set(('call', 'jump'))

    op_info['one_reg_opcodes'] = set(('rl', 'rr', 'sl0', 'sl1', 'sla', 'slx', 'sr0', 'sr1', 'sra', 'srx', \
      'hwbuild'))

    op_info['two_reg_opcodes'] = set(('add', 'addcy', 'and', 'compare', 'fetch', 'input', \
      'load', 'or', 'output', 'store', 'sub', 'subcy', 'test', 'xor', \
      'comparecy', 'testcy'))
    op_info['two_reg_op_offset'] = -0x1000

    op_info['directives'] = set(('address', 'constant', 'namereg', \
        'include', 'default_jump', 'string', 'table'))

  return op_info



def fail(s, loc, tokens):
  raise ParseFatalException(s, loc, 'Unknown token "{}", s:"{}", loc:"{}"'.format(tokens[0], s, loc))


def picoblaze_parser(op_info):
  '''Creates a Pyparsing parser object that processes individual lines of assembly'''
  EOL = StringEnd() #Suppress(OneOrMore(LineEnd()))

  base_identifier = Word(alphanums + '_', alphanums + '_').setName('identifier')
  not_identifier = Combine(Literal('~') + base_identifier)
  env_identifier = Combine(Literal('%') + base_identifier)
  addr_identifier = Combine(base_identifier + (Literal("'upper") | Literal("'lower")))

  if not op_info['has_string_table_support']:
    identifier = (not_identifier | env_identifier | addr_identifier | \
      base_identifier)
  else:
    string_identifier = Combine(base_identifier + '$')
    table_identifier = Combine(base_identifier + '#')
    identifier = (not_identifier | env_identifier | string_identifier | \
      table_identifier | addr_identifier | base_identifier)

  hex_literal = Word(nums + srange('[a-fA-F]'))
  bin_literal = Combine(Word('01') + "'b")
  dec_literal = Combine(Word(nums) + "'d")
  string_literal = dblQuotedString.setName('string')
  q_string_literal = Combine(Literal('""') + Word(string.printable.translate(None, '"')) + Literal('""'))
  literal = (q_string_literal | string_literal | dec_literal | bin_literal | hex_literal)

  table_def = Group(Suppress('[') + delimitedList(hex_literal) + \
      (Literal("]'d") | Literal("]'b") | Literal("]"))).setResultsName('table')


  label = (base_identifier + Suppress(':')).setResultsName('label')

  comment = (Suppress(';') + restOfLine + EOL).setName('comment').setResultsName('comment')

  #bad_tok = Word(alphas).setParseAction(fail)

  inst_kw = Or([CaselessKeyword(k) for k in op_info['opcodes'].keys()])

  reg_keys = ['s{}'.format(n) for n in xrange(10)] + ['sa', 'sb', 'sc', 'sd', 'se', 'sf']
  reg_kw = Or([CaselessKeyword(k) for k in reg_keys])

  directive = Or([CaselessKeyword(k) for k in op_info['directives']])

  indirect_reg = Group(Suppress('(') + (reg_kw | identifier) + Suppress(')')).setResultsName('ireg')
  indirect_addr = Group(Suppress('(') + (reg_kw | identifier) + Suppress(',') + \
      (reg_kw | identifier) + Suppress(')')).setResultsName('iaddr')

  instruction = Group((inst_kw | directive) + Optional( \
      ((literal ^ reg_kw ^ identifier) + \
      Optional(Suppress(',') + (literal ^ reg_kw ^ identifier ^ indirect_reg ^ table_def)) \
      ) | indirect_addr \
    )).setResultsName('instruction')

  cmd = instruction + Optional(comment) + EOL

  empty_label = label + (comment | EOL)

  statement = Group(empty_label | label + cmd | cmd | comment | EOL).setResultsName('statement')

  return statement


class Statement(object):
  '''Low level representation of a statement (instructions, directives, comments)'''
  def __init__(self, ptree, line):
    '''
    ptree : pyparsing parse tree object for a single statement
    line : source line number
    '''
    self.line = line
    self.label = ptree['label'][0] if 'label' in ptree else None
    self.comment = ptree['comment'][0] if 'comment' in ptree else None

    self.command = None
    self.arg1 = None
    self.arg2 = None
    self.indirect_reg = False
    self.indirect_addr = False
    self.table_def = False

    if 'instruction' in ptree:
      ifields = ptree['instruction']
      self.command = ifields[0]

      if len(ifields) > 1:
        if 'iaddr' in ifields: # Indirect address (e.g. jump@ (s1, s2))
          self.arg1 = ifields[1][0]
          self.arg2 = ifields[1][1]
          self.indirect_addr = True

        else: # Normal operand
          self.arg1 = ifields[1]
      if len(ifields) > 2:
        if 'table' in ifields:
          self.arg2 = ifields[2]
          self.table_def = True
        elif 'ireg' in ifields:
          self.arg2 = ifields[2][0]
          self.indirect_reg = True
        else:
          self.arg2 = ifields[2]

    # Instruction fields
    self.address = 0
    self.opcode = 0
    self.regx = 0
    self.regy = 0
    self.immediate = 0


  def machine_word(self):
    '''Returns the numeric value of the assembled instruction'''
    return self.opcode + (self.regx << 8) + (self.regy << 4) + self.immediate

  def is_instruction(self):
    '''Identify if this statement is an instruction (vs. directive)'''
    if self.command is None: return False
    if self.command in ('address', 'constant', 'namereg', 'include', 'default_jump', \
        'string', 'table'): return False
    return True

  def format(self, upper=True, show_addr=False, colorize=False):
    '''Generate a formatted string for the statement
    upper : Upper case instructions and directives
    show_addr : Include assembled memory address and machine word
    '''
    label = self.label + ':' if self.label is not None else ''
    comment = ';' + self.comment if self.comment is not None else ''
    inst = ''
    if self.command is not None:
      inst = self.command
      if upper: inst = inst.upper()

      if self.indirect_addr:
        inst += ' ({}, {})'.format(self.arg1, self.arg2)
      else:
        if self.arg1 is not None:
          inst += ' ' + self.arg1
        if self.arg2 is not None:
          if self.indirect_reg:
            inst += ', (' + self.arg2 + ')'
          elif self.table_def:
            inst += ', [' + ', '.join(self.arg2[:-1]) + self.arg2[-1]
          else:
            inst += ', ' + self.arg2

    if show_addr:
      if self.is_instruction():
        op = '{:05X}'.format(self.machine_word())
        op = note(op) if colorize else op # blue text
        addr = '{:03X}  {}'.format(self.address, op)
      else:
        addr = '          '
    else:
      addr = ''

    if colorize:
      if len(comment) > 0:
        comment = success(comment) # green text
      if len(label) > 0:
        label = error(label) # red text

    if len(inst) > 0:
      return '{}{:>20} {:30} {}'.format(addr, label, inst, comment).rstrip()
    else:
      return '{}{:>20} {}'.format(addr, label, comment).rstrip()


class Symbol(object):
  '''Entry object for symbol tables (labels, constants, registers, strings, tables)'''
  def __init__(self, name, value, val_text=None, source_file=None, source_line=-1):
    self.name = name
    self.value = value
    self._val_text = val_text
    self.source_file = source_file
    self.source_line = source_line
    self.in_use = False # Track use of labels

  @property
  def val_text(self):
    '''Returns string value for the symbol'''
    if self._val_text is None:
      try:
        return '{:02X}'.format(self.value)
      except ValueError:
        return str(self.value)
    else:
      return self._val_text


def parse_lines(lines, op_info):
  '''Parse a list of text lines into Statement objects'''
  parser = picoblaze_parser(op_info)

  statements = []
  for i, l in enumerate(lines):
    try:
      ptree = parser.parseString(l)
    except ParseException, e:
      print(error('PARSE ERROR:') + ' bad statement in line {}:\n  {}'.format(i, l))
      #print('>>>', e)
      #raise
      sys.exit(1)

    statements.append(Statement(ptree['statement'], i+1))

  return statements


class Assembler(object):
  '''Main object for running assembler and tracking symbol information'''
  def __init__(self, top_source_file, timestamp, options, upper_env_names): #FIXME
    self.top_source_file = top_source_file
    self.mem_size = options.mem_size
    self.scratch_size = options.scratch_size
    self.use_pb6 = options.use_pb6
    self.timestamp = timestamp

    self.constants = self._init_constants()
    self.labels = {}

    hex_digits = [hex(d)[-1] for d in xrange(16)]
    self.registers = dict(('s' + h, i) for i, h in enumerate(hex_digits))
    self.strings = self._init_strings()
    self.tables = {}

    self.sources = {}
    self.default_jump = None

    self.op_info = get_op_info(options.use_pb6)
    self.upper_env_names = upper_env_names


  def _init_constants(self):
    '''Initialize the constant symbol table with the
       Picoblaze-6 automatic timestamp and datestamp values'''

    constants = {
      'timestamp_hours'   : Symbol('timestamp_hours', self.timestamp.hour),
      'timestamp_minutes' : Symbol('timestamp_minutes', self.timestamp.minute),
      'timestamp_seconds' : Symbol('timestamp_seconds', self.timestamp.second),
      # Leave some work for someone to fix in Y3K
      'datestamp_year'    : Symbol('timestamp_year', self.timestamp.year - 2000),
      'datestamp_month'   : Symbol('timestamp_month', self.timestamp.month),
      'datestamp_day'     : Symbol('timestamp_day', self.timestamp.day),

      'NUL' : Symbol('NUL', 0x00),
      'BEL' : Symbol('BEL', 0x07),
      'BS'  : Symbol('BS', 0x08),
      'HT'  : Symbol('HT', 0x09),
      'LF'  : Symbol('LF', 0x0a),
      'VT'  : Symbol('VT', 0x0b),
      'CR'  : Symbol('CR', 0x0d),
      'ESC' : Symbol('ESC', 0x1b),
      'DEL' : Symbol('DEL', 0x7f),
      'DCS' : Symbol('DCS', 0x90),
      'ST'  : Symbol('ST', 0x9c)
    }

    return constants


  def _init_strings(self):
    '''Initialize predefined strings'''
    ts = self.timestamp.strftime('%H:%M:%S')
    ds = self.timestamp.strftime('%d %b %Y')
    strings = {
      'timestamp$' : Symbol('timestamp$', ts, '"{}"'.format(ts)),
      'datestamp$' : Symbol('datestamp$', ds, '"{}"'.format(ds)),
    }

    return strings



  def process_includes(self, source_file=None):
    '''Scan a list of statements for INCLUDE directives and recursively
    read each included source file. Constant, string, and table definitions
    are also processed to keep track of where they are defined.
    This is a generator function that yields the name of each included file'''
    if source_file is None: source_file = self.top_source_file
    if source_file in self.sources: return

    yield source_file
    with open(source_file, 'r') as fh:
      source = [s.rstrip() for s in fh.readlines()]

    slist = parse_lines(source, self.op_info)
    self.sources[source_file] = slist

    # Scan for include directives
    for s in slist:
      # Track label sources
      if s.label is not None:
        if s.label in self.labels:
          raise FatalError(s, 'Redefinition of label:', s.label)

        self.labels[s.label] = Symbol(s.label, -1, source_file=source_file, source_line=s.line)

      # Recursively include additional sources
      if s.command == 'include':
        if s.arg1 is not None and s.arg1[0] == '"' and s.arg1[-1] == '"':
          include_file = s.arg1[1:-1]
          # If the included file has a relative path build it off of the current path
          if not os.path.isabs(include_file):
            include_file = os.path.join(os.path.dirname(source_file), include_file)

          if not os.path.exists(include_file):
            raise FatalError(s, 'Include file not found:', include_file)

          for inc_file in self.process_includes(include_file):
            yield inc_file
        else:
          raise FatalError(s, 'Invalid include parameter', s.arg1)

      # Handle constant definitions before flattening
      elif s.command == 'constant':
        if s.arg1 is None or s.arg2 is None:
          raise FatalError(s, 'Missing argument to constant directive')

        if s.arg1 in self.constants:
          raise FatalError(s, 'Redefinition of constant:', s.arg1)

        # Prevent the use of 3 or less character constants that are valid hex literals
        if len(s.arg1) <= 3 and hex_to_int(s.arg1) is not None:
          raise FatalError(s, 'Invalid constant. Conflicts with hex literal', s.arg1)

        if s.arg2[0] == '%': # Look up env variable
          ename = s.arg2[1:]
          if ename.upper() not in self.upper_env_names:
            raise FatalError(s, 'Unknown environment variable:', ename)
          ename = self.upper_env_names[ename.upper()]
          cval = convert_literal(os.getenv(ename))
          self.constants[s.arg1] = Symbol(s.arg1, cval, val_text=s.arg2, \
              source_file=source_file, source_line=s.line)

        else: # Normal literal constant
          cval = convert_literal(s.arg2)
          self.constants[s.arg1] = Symbol(s.arg1, cval, val_text=s.arg2, \
              source_file=source_file, source_line=s.line)

      elif s.command == 'string':
        if s.arg1 is None or s.arg2 is None:
          raise FatalError(s, 'Missing argument to STRING directive')
        if s.arg1[-1] != '$':
          raise FatalError(s, 'Invalid string name (missing $):', s.arg1)
        if s.arg1 in self.strings:
          raise FatalError(s, 'Redefinition of string:', s.arg1)
        if s.arg2[0] != '"' or s.arg2[-1] != '"':
          asm.error('Not a valid string:', s.arg2)

        self.strings[s.arg1] = Symbol(s.arg1, s.arg2[1:-1], s.arg2, \
            source_file=source_file, source_line=s.line)

      elif s.command == 'table':
        if s.arg1 is None or s.arg2 is None:
          raise FatalError(s, 'Missing argument to TABLE directive')
        if s.arg1[-1] != '#':
          raise FatalError(s, 'Invalid table name (missing #):', s.arg1)
        if s.arg1 in self.strings:
          raise FatalError(s, 'Redefinition of table:', s.arg1)
        if s.table_def is False:
          raise FatalError(s, 'Missing table definition')

        # Determine the radix of the elements
        if s.arg2[-1].endswith('d'):
          radix = 10
        elif s.arg2[-1].endswith('b'):
          radix = 2
        else:
          radix = 16

        # Convert the table elements to integers
        try:
          tbl = [int(e, radix) for e in s.arg2[:-1]]
        except ValueError:
          raise FatalError(s, 'Invalid table element (radix {})'.format(radix))

        val_text = '[' + ', '.join(s.arg2[:-1]) + s.arg2[-1]
        self.tables[s.arg1] = Symbol(s.arg1, tbl, val_text, \
          source_file=source_file, source_line=s.line)


  def flatten_includes(self, slist, include_stack=None):
    '''Generator function that produces a flattened list of statements
    after evaluating INCLUDE directives.
    slist : List of statements from top-level source file
    include_stack : Stack of parent source files used to detect recursive includes
    '''
    if include_stack is None: include_stack = [self.top_source_file]

    for s in slist:
      if s.command == 'include':
        include_file = s.arg1[1:-1]
        if include_file in include_stack:
          raise FatalError(s, 'Recursive include:', s.arg1)
        else:
          include_stack.append(include_file)
          islist = list(self.flatten_includes(self.sources[include_file], include_stack))
          include_stack.pop()
          for i in islist:
            yield copy.copy(i)
      else:
        yield s


  def get_address(self, addr_label):
    '''Lookup the address assigned to addr_label'''
    if addr_label in self.labels:
      self.labels[addr_label].in_use = True
      return self.labels[addr_label].value
    else:
      return convert_literal(addr_label)

  def get_constant(self, arg):
    '''Lookup the constant or literal value associated with arg'''
    invert_value = False
    if arg[0] == '~':
      invert_value = True
      arg = arg[1:]

    if arg.endswith("'upper") or arg.endswith("'lower"):
      # Address constant
      label, portion = arg.split("'")
      addr = self.get_address(label)
      if addr is None:
        return None

      if portion == 'lower':
        value = addr & 0xFF
      else:
        value = (addr >> 8) & 0xF

    elif arg in self.constants: # Normal constant
      value = self.constants[arg].value
    else: # Attempt to convert a constant literal
      value = convert_literal(arg)

    if invert_value and value is not None:
      value = (~value) & 0xFF

    return value

  def get_register(self, arg):
    '''Lookup the register named in arg'''
    if arg in self.registers:
      return self.registers[arg]
    return None

  def get_string(self, name):
    '''Lookup the string associated with name'''
    if name in self.strings:
      return self.strings[name].value
    return None

  def get_table(self, name):
    '''Lookup the table associated with name'''
    if name in self.tables:
      return self.tables[name].value
    return None


  def statement_words(self, s):
    '''Determine the number of words generated for each instruction

    Normally this is 1 but the OUTPUTK and LOAD&RETURN instructions are
    replicated if a string or table is passed as an operand.
    s : Statement object
    '''
    if s.is_instruction():
      num_words = 1

      array_name = None
      if s.command == 'outputk':
        if s.arg1 is not None and s.arg1[-1] in ('$', '#'):
          array_name = s.arg1

      elif s.command == 'load&return':
        if s.arg2 is not None and s.arg2[-1] in ('$', '#'):
          array_name = s.arg2

      if array_name is not None:
        if array_name[-1] == '$':
          if array_name not in self.strings:
            raise FatalError(s, 'Unknown string:', array_name)
          num_words = len(self.strings[array_name].value)
    
        else: # Table
          if array_name not in self.tables:
            raise FatalError(s, 'Unknown table:', array_name)
          num_words = len(self.tables[array_name].value)

      return num_words
    else:
      return 0


  def assemble(self):
    '''Generate assembled instructions
    Returns a list of Statement objects with filled in instruction fields
    '''
    cur_addr = 0
    # Pass 1: Flatten includes
    slist = list(self.flatten_includes(self.sources[self.top_source_file]))

    # Pass 2: Set instruction and label addresses
    for s in slist:
      if s.label is not None:
        self.labels[s.label].value = cur_addr

      if s.is_instruction():
        if cur_addr >= self.mem_size:
          raise FatalError(s, 'Address exceeds memory bounds: {:03X} (limit {:03X})'.format(\
            cur_addr, self.mem_size-1))
        s.address = cur_addr
        cur_addr += self.statement_words(s) # Move to next address. Could be > 1 if a string or table operand

      elif s.command == 'address':
        cur_addr = convert_literal(s.arg1)
        if cur_addr is None:
          raise FatalError(s, 'Invalid address:', s.arg1)

        if cur_addr >= self.mem_size:
          raise FatalError(s, 'Address exceeds memory bounds: {:03X} (limit {:03X})'.format(\
            cur_addr, self.mem_size-1))


    # Pass 3: Validate and assemble instructions
    instructions = []
    for s in slist:

      if s.is_instruction():
        # Verify instruction is valid
        if s.command not in self.op_info['opcodes']:
          raise FatalError(s, 'Invalid Picoblaze-{} instruction:'.format( \
            6 if self.use_pb6 else 3), s.command)

        s.opcode = self.op_info['opcodes'][s.command] # Set base opcode

        if s.command in self.op_info['flag_opcodes']:
          # Check if first argument is a flag
          addr_label = s.arg1
          if s.arg1 is not None:
            if s.command == 'return':
              flag_codes = self.op_info['return_flag_codes']
            else:
              flag_codes = self.op_info['flag_codes']

            if s.arg1.lower() in flag_codes:
              s.opcode += flag_codes[s.arg1.lower()]
              addr_label = s.arg2

          if s.command in self.op_info['addr_opcodes']: # Include address for call and jump
            if addr_label is None:
              raise FatalError(s, 'Missing address')

            s.immediate = self.get_address(addr_label)
            if s.immediate is None:
              raise FatalError(s, 'Invalid address:', addr_label)
            if s.immediate >= self.mem_size:
              raise FatalError(s, 'Out of range address')

        elif s.command in self.op_info['one_reg_opcodes']:
          if s.arg1 is None:
            raise FatalError(s, 'Missing operand')
          if s.arg2 is not None:
            raise FatalError(s, 'Illegal operand:', s.arg2)

          s.regx = self.get_register(s.arg1)
          if s.regx is None:
            raise FatalError(s, 'Invalid register:', s.arg1)

        elif s.command in self.op_info['two_reg_opcodes']:
          if s.arg1 is None or s.arg2 is None:
            raise FatalError(s, 'Missing operand')

          s.regx = self.get_register(s.arg1)
          if s.regx is None:
            raise FatalError(s, 'Invalid register:', s.arg1)

          s.regy = self.get_register(s.arg2)
          if s.regy is not None: # Using y register opcode
            s.opcode += self.op_info['two_reg_op_offset'] # Adjust opcode

          else: # The second arg was not a register
            s.regy = 0
            s.immediate = self.get_constant(s.arg2)

            if s.immediate is None:
              raise FatalError(s, 'Invalid operand:', s.arg2)
            if not (0 <= s.immediate < 256):
              raise FatalError(s, 'Immediate value out of range:', s.immediate)

            if s.command in ('fetch', 'store'):
              if s.immediate >= self.scratch_size:
                raise FatalError(s, 'Scratchpad address out of range:', hex(s.immediate))

        elif s.command in ('enable', 'disable'):
          if s.arg1 is None:
            raise FatalError(s, 'Missing operand')
          if s.arg1.lower() != 'interrupt' or s.arg2 is not None:
            raise FatalError(s, 'Invalid operand to {}'.format(s.command.upper()))

        elif s.command == 'returni':
          if s.arg1 is None:
            raise FatalError(s, 'Missing operand')
          if s.arg1.lower() not in ('enable', 'disable'):
            raise FatalError(s, 'Invalid operand to RETURNI')

          if s.arg1.lower() == 'enable':
            s.opcode += 1

        # Irregular Picoblaze-6 instructions
        elif s.command in ('call@', 'jump@'):
          if s.arg1 is None or s.arg2 is None:
            raise FatalError(s, 'Missing operand')
          s.regx = self.get_register(s.arg1)
          if s.regx is None:
            raise FatalError(s, 'Invalid register:', s.arg1)

          s.regy = self.get_register(s.arg2)
          if s.regy is None:
            raise FatalError(s, 'Invalid register:', s.arg2)

        elif s.command == 'load&return':
          if s.arg1 is None or s.arg2 is None:
            raise FatalError(s, 'Missing operand')

          s.regx = self.get_register(s.arg1)
          if s.regx is None:
            raise FatalError(s, 'Invalid register:', s.arg1)

          elems = []
          if s.arg2.endswith('$'):
            elems = [(ord(e), '"{}"'.format(e)) for e in self.strings[s.arg2].value]
          elif s.arg2.endswith('#'):
            elems = [(e, '{:02X}'.format(e)) for e in self.tables[s.arg2].value]

          if len(elems) > 0:
            for i, (e, e_text) in enumerate(elems):
              new_s = copy.copy(s)
              new_s.immediate = e
              new_s.arg2 = e_text
              new_s.address += i
              if i > 0: new_s.comment = None
              instructions.append(new_s)
            continue

          else:
            s.immediate = self.get_constant(s.arg2)
            if s.immediate is None:
              raise FatalError(s, 'Invalid operand:', s.arg2)


        elif s.command == 'outputk':
          if s.arg1 is None or s.arg2 is None:
            raise FatalError(s, 'Missing operand')

          port = self.get_constant(s.arg2)
          if port is None:
            raise FatalError(s, 'Invalid operand:', s.arg2)
          if not 0 <= port < 16:
            raise FatalError(s, 'Invalid port for OUTPUTK:', s.arg2)

          elems = []
          if s.arg1.endswith('$'):
            elems = [(ord(e), '"{}"'.format(e)) for e in self.strings[s.arg1].value]
          elif s.arg1.endswith('#'):
            elems = [(e, '{:02X}'.format(e)) for e in self.tables[s.arg1].value]

          if len(elems) > 0:
            for i, (e, e_text) in enumerate(elems):
              new_s = copy.copy(s)
              new_s.immediate = (e << 4) + port
              new_s.arg1 = e_text
              new_s.address += i
              if i > 0: new_s.comment = None
              instructions.append(new_s)
            continue

          else:
            const = self.get_constant(s.arg1)
            if const is None:
              raise FatalError(s, 'Invalid operand:', s.arg1)

          s.immediate = (const << 4) + port

        elif s.command == 'regbank':
          if s.arg1 is None:
            raise FatalError(s, 'Missing operand')
          if s.arg1.lower() not in ('a', 'b'):
            raise FatalError(s, 'Invalid operand to REGBANK')

          if s.arg1.lower() == 'b':
            s.opcode += 1

        elif s.command == 'star':
          if s.arg1 is None or s.arg2 is None:
            raise FatalError(s, 'Missing operand')

          # The STAR instruction has special rules for RegX (arg1)
          # It MUST be in the form: s[hexdigit]
          # We skip the usual table lookup for arg1
          if len(s.arg1) == 2 and s.arg1[0].lower() == 's' and s.arg1[1] in string.hexdigits:
            s.regx = int(s.arg1[1], 16)
          else:
            raise FatalError(s, 'Invalid register:', s.arg1)

          s.regy = self.get_register(s.arg2)
          if s.regy is None:
            raise FatalError(s, 'Invalid register:', s.arg2)

        elif s.command == 'inst':
          # NOTE: INST is really a directive but we need to reserve a space in the
          # address map for its value so we treat it as an instruction with 0x00 opcode.

          if s.arg1 is None:
            raise FatalError(s, 'Missing operand')
          s.immediate = convert_literal(s.arg1)
          if s.immediate is None or not 0 <= s.immediate < 2**18:
            raise FatalError(s, 'Invalid INST value:', s.arg1)

        else:
          raise FatalError(s, 'Unknown instruction:', s.command)


      else: # Not an instruction
        if s.command == 'namereg':
          if s.arg1 is None or s.arg2 is None:
            raise FatalError(s, 'Missing argument to NAMEREG directive')
          if s.arg1 not in self.registers:
            raise FatalError(s, 'Unknown register name:', s.arg1)

          self.registers[s.arg2] = self.get_register(s.arg1)
          del self.registers[s.arg1]


        elif s.command == 'default_jump':
          if self.default_jump is not None:
            raise FatalError(s, 'Redefinition of default jump')
          if s.arg2 is not None:
            raise FatalError(s, 'Too many arguments to DEFAULT_JUMP')

          self.default_jump = self.get_address(s.arg1)
          if self.default_jump is None:
            raise FatalError(s, 'Invalid address:', s.arg1)

      instructions.append(s)

    # Create default jump instruction
    if self.default_jump is None:
      self.default_jump = 0
    else:
      self.default_jump = self.op_info['opcodes']['jump'] + self.default_jump


    return instructions


def hex_to_int(s):
  '''Convert a hex string literal into an integer. Returns None on failure.'''
  try:
    return int(s, 16) #int('0x' + s, 0)
  except ValueError:
    return None

def convert_literal(arg):
  '''Convert a string literal into an integer. Returns None on failure.'''
  if "'d" in arg: # Decimal literal
    try:
      return int(arg[:-2])
    except ValueError:
      return None
  elif "'b" in arg: # Binary literal
    try:
      return int(arg[:-2], 2)
    except ValueError:
      return None
  elif '"' in arg and len(arg) == 3: # Character literal
    return ord(arg[1])
  else: # Assume it is a hex literal
    return hex_to_int(arg)


def asm_error(*args, **kwargs):
  '''Print an error message'''
  print(error('\nERROR:'), *args, file=sys.stderr)
  if 'statement' in kwargs:
    s = kwargs['statement']
    print( '  line {}:  {}'.format(s.line, s.format().lstrip()))
  if 'exit' in kwargs:
    sys.exit(kwargs['exit'])


#class OPBAsmApp(object):
#  def __init__(self, options):
#    self.options = options

#    # Build map of environment variables in upper case
#    # This allows the same case insensitive behavior on Linux as Windows.
#    self.upper_env_names = dict(((k.upper(), k) for k in os.environ.keys()))



def parse_command_line():
  '''Process command line arguments'''
  progname = os.path.basename(sys.argv[0])
  usage = '''{} [-i] <input file> [-n <name>] [-t <template>] [-6] [-m <mem size>] [-s <scratch size>]
       {} -g'''.format(progname, progname)
  parser = OptionParser(usage=usage)

  parser.add_option('-i', '--input', dest='input_file', help='Input file')
  parser.add_option('-n', '--name', dest='module_name', help='Module or entity name (defaults to input file name)')
  parser.add_option('-t', '--template', dest='template_file', help='Template file')
  parser.add_option('-6', '--pb6', dest='use_pb6', action='store_true', default=False, \
        help='Assemble Picoblaze-6 code')
  parser.add_option('-m', '--mem-size', dest='mem_size', \
                    default=0, type=int, help='Program memory size')
  parser.add_option('-s', '--scratch-size', dest='scratch_size', \
                    default=0, type=int, help='Scratchpad memory size')
  parser.add_option('-x', '--hex', dest='hex_output', action='store_true', default=False, \
        help='Write HEX in place of MEM file')
  parser.add_option('-c', '--color-log', dest='color_log', action='store_true', default=False, \
        help='Colorize log file')
  parser.add_option('-g', '--get-templates', dest='get_templates', action='store_true', default=False, \
        help='Get default template files')
  parser.add_option('-v', '--version', dest='version', action='store_true', default=False, \
        help='Show OPBASM version')

  options, args = parser.parse_args()

  if options.version:
    print('OPBASM version', __version__)
    sys.exit(0)

  if not options.get_templates:
    if not options.input_file:
      if len(args) > 0:
        options.input_file = args[0]

    if not options.input_file: parser.error('Missing input file')

    if not options.module_name:
      options.module_name = os.path.splitext(os.path.basename(options.input_file))[0]

    if options.use_pb6:
      scratch_sizes = (64, 128, 256)
      max_mem_size = 4096
    else: # PB3
      scratch_sizes = (64,)
      max_mem_size = 1024

    if options.scratch_size == 0:
      options.scratch_size = max(scratch_sizes)
    elif options.scratch_size not in scratch_sizes:
      parser.error('Invalid scratchpad size')

    if options.mem_size == 0:
      options.mem_size = max_mem_size
    elif options.mem_size > max_mem_size:
      parser.error('Memory size is too large')


  return options


def build_memmap(slist, mem_size, default_jump):
  '''Insert assembled instructions into a memory array'''
  # Ensure mem size is a power of 2
  addr_bits = (mem_size-1).bit_length()
  adj_mem_size = 2 ** addr_bits

  mmap = [default_jump] * adj_mem_size
  for s in slist:
    if s.is_instruction():
      mmap[s.address] = s.machine_word()
  return mmap


def write_hex_file(fname, mmap):
  '''Write a memory map as a hex or mem format file'''
  with open(fname, 'w') as fh:
    if fname.endswith('.mem'):
      print('@00000000', file=fh)
    for m in mmap:
      print('{:05X}'.format(m), file=fh)


def get_timestamp():
  '''Get a current datestamp'''
  return datetime.datetime.now().replace(microsecond=0)

def code_stats(assembled_code):
  '''Analyze assembled code to determine addressing parameters'''
  inst_count = 0
  last_inst = None
  for s in assembled_code:
    if s.is_instruction():
      inst_count += 1
      last_inst = s

  if last_inst is not None:
    addr_bits = max(10, last_inst.address.bit_length())
    last_addr = last_inst.address
  else:
    addr_bits = 10
    last_addr = 0

  nom_size = 2 ** addr_bits

  stats = {
    'inst_count': inst_count,
    'addr_bits': addr_bits,
    'last_addr': last_addr,
    'nom_size': nom_size
  }

  return stats

def instruction_usage(assembled_code, asm):
  '''Analyze assembled code to determine instruction histogram'''
  stats = dict((k, 0) for k in asm.op_info['opcodes'].keys())
  del stats['inst'] # No a real opcode

  for s in assembled_code:
    if s.is_instruction() and s.command in stats:
      stats[s.command] += 1

  return stats


def underline(s, char='-'):
  '''Insert an underline aligned to a text string'''
  vis_len = len(s.strip())
  return '{}\n{}'.format(s, ' ' * (len(s) - vis_len) + char * vis_len)


def format_table(rows, col_names, indent=0):
  '''Format tabular data with variable width columns
  Returns a list of strings
  '''
  cols = zip(col_names, *rows)
  col_size = [max(len(str(i)) for i in col) for col in cols]

  fmt = ' ' * indent + '  '.join('{{:{}}}'.format(w) for w in col_size)
  tbl = [fmt.format(*col_names),
    fmt.format(*['-'*len(c) for c in col_names])
  ]
  for r in rows:
    tbl.append(fmt.format(*['' if i is None else str(i) for i in r]).rstrip())

  return tbl


def write_log_file(log_file, assembled_code, stats, asm, colorize):
  '''Write a log file with details of assembled code'''
  with open(log_file, 'w') as fh:
    def printf(*args):
      return print(*args, file=fh)

    printf('Open Picoblaze Assembler log for program "{}"'.format(asm.top_source_file))
    printf('Generated by opbasm v', __version__)
    printf('  Assembled on {}'.format(asm.timestamp.isoformat()))
    printf('  Picoblaze-{} mode\n'.format(6 if asm.use_pb6 else 3))

    printf('  Last occupied address: {:03X} hex'.format(stats['last_addr']))
    printf('  Nominal program memory size: {}K ({})  address({}:0)'.format( \
                stats['nom_size'] // 1024, stats['nom_size'], stats['addr_bits']-1))
    printf('  Actual memory size:', asm.mem_size)
    printf('  Occupied memory locations:', stats['inst_count'])
    printf('  Memory locations available:', asm.mem_size - stats['inst_count'])
    printf('  Scratchpad size:', asm.scratch_size)

    printf('\n\n' + underline('Assembly listing'))
    for s in assembled_code:
      printf(s.format(show_addr=True, colorize=colorize))

    printf('\n\n' + underline('PSM files that have been assembled'))
    for f in asm.sources.keys():
      printf('   ', os.path.abspath(f))

    printf('\n\n' + underline('List of defined constants'))
    headings = ['CONSTANT name', 'Value', 'Source PSM file']
    rows = [(c, asm.constants[c].val_text, asm.constants[c].source_file) \
      for c in sorted(asm.constants.keys())]
    for r in format_table(rows, headings, indent=3):
      printf(r)

      

    if len(asm.tables) == 0:
      printf('\n\n  No tables defined')
    else:
      printf('\n\n' + underline('List of defined tables'))
      headings = ['TABLE name', 'Value', 'Source PSM file']
      rows = [(t, asm.tables[t].val_text, asm.tables[t].source_file) \
        for t in sorted(asm.tables.keys())]
      for r in format_table(rows, headings, indent=3):
        printf(r)



    printf('\n\n' + underline('List of text strings'))
    headings = ['STRING name', 'Value', 'Source PSM file']
    rows = [(s, asm.strings[s].val_text, asm.strings[s].source_file) \
      for s in sorted(asm.strings.keys())]
    for r in format_table(rows, headings, indent=3):
      printf(r)
    

    printf('\n\n' + underline('List of line labels'))
    show_caption = not all(l.in_use for l in asm.labels.values())
    headings = ['   Label', 'Addr', 'Source PSM file']
    rows = [(('   ' if asm.labels[l].in_use else '*  ') + l, \
      '{:03X}'.format(asm.labels[l].value), asm.labels[l].source_file) \
      for l in sorted(asm.labels.keys())]
    for r in format_table(rows, headings, indent=1):
      printf(r)

    if show_caption:
      printf('\n       * Unreferenced label(s)')


    printf('\n\n' + underline('Instruction usage statistics'))
    inst_usage = instruction_usage(assembled_code, asm)
    headings = ['Instruction', 'Instances']
    rows = [(i.upper(), inst_usage[i] if inst_usage[i] > 0 else '-') \
      for i in sorted(inst_usage.keys())]
    for r in format_table(rows, headings, indent=3):
      printf(r)



def build_xilinx_mem_init(mmap, split_data=False):
  '''Create a dict of Xilinx BRAM INIT and INITP strings'''
  minit = {}

  if not split_data: # Map to 18-bit BRAMs
    # Lower 16-bits are put in INIT
    for a in xrange(len(mmap) // 16):
      mline = mmap[a*16:(a+1)*16]
      #print('@@@ mline len', len(mline))
      init = ''.join('{:04X}'.format(w & 0xFFFF) for w in reversed(mline))
      minit['INIT_{:02X}'.format(a)] = init

    # Upper 2-bits are put in INITP
    for a in xrange(len(mmap) // 128):
      mline = mmap[a*128:(a+1)*128]
      nibbles = []
      for i in xrange(0, len(mline), 2):
        nibbles.append((mline[i] >> 16) + ((mline[i+1] >> 14) & 0xC))

      init = ''.join('{:01X}'.format(n & 0xF) for n in reversed(nibbles))
      minit['INITP_{:02X}'.format(a)] = init

  else: # Map to 9-bit BRAMs
    # Split the mem-map into 9-bit halves
    mmap_l = []
    mmap_h = []
    for m in mmap:
      l = m & 0x1FF
      h = (m >> 9) & 0x1FF
      mmap_l.append(l)
      mmap_h.append(h)

    build_9_bit_mem_init(mmap_l, minit, '8:0')
    build_9_bit_mem_init(mmap_h, minit, '17:9')

  return minit


def build_9_bit_mem_init(mmap, minit, bit_range):
  '''Compute Xilinx BRAM INIT and INITP strings for 9-bit split memories'''
  # Lower 8-bits are put in INIT
  for a in xrange(len(mmap) // 32):
    mline = mmap[a*32:(a+1)*32]
    init = ''.join('{:02X}'.format(w & 0xFF) for w in reversed(mline))
    minit['[{}]_INIT_{:02X}'.format(bit_range, a)] = init

  # Upper 1-bits are put in INITP
  for a in xrange(len(mmap) // 256):
    mline = mmap[a*256:(a+1)*256]
    nibbles = []
    for i in xrange(0, len(mline), 4):
      nibbles.append((mline[i] >> 8) + ((mline[i+1] >> 7) & 0x02) + \
        ((mline[i+2] >> 6) & 0x04) + ((mline[i+3] >> 5) & 0x08))
      #nibbles.append((mline[i] >> 16) + ((mline[i+1] >> 14) & 0xC))

    init = ''.join('{:01X}'.format(n & 0xF) for n in reversed(nibbles))
    minit['[{}]_INITP_{:02X}'.format(bit_range, a)] = init


def write_hdl_file(input_file, hdl_file, hdl_template, minit, timestamp):
  '''Insert INIT strings and other fields into an HDL template'''
  # Read template
  with open(hdl_template, 'r') as fh:
    template = fh.readlines()

  # Remove template header
  found_header = -1
  for i, l in enumerate(template):
    if '{begin template}' in l:
      found_header = i
      break

  if found_header >= 0:
    hdl = ''.join(template[found_header+1:])
  else:
    hdl = ''.join(template)

  # Substitute template tags
  for k, v in minit.iteritems():
    hdl = hdl.replace('{{{}}}'.format(k), v)

  hdl = hdl.replace('{source file}', input_file)  # Extension not used by KCPSM3.exe
  hdl = hdl.replace('{name}', os.path.splitext(hdl_file)[0])
  hdl = hdl.replace('{timestamp}', timestamp)

  with open(hdl_file, 'w') as fh:
    fh.write(hdl)


def find_templates(template_file):
  '''Search for HDL template files'''
  templates = {}
  if template_file is not None:
    if os.path.exists(template_file):
      ext = os.path.splitext(template_file)[1]
      if ext.lower() in ('.vhd', 'vhdl'):
        templates['vhdl'] = template_file
      else:
        templates['verilog'] = template_file

  else: # Search for standard templates
    vhdl_templates = ('ROM_form.vhd', 'ROM_form.vhdl')
    verilog_templates = ('ROM_form.v',)

    for f in vhdl_templates:
      if os.path.exists(f):
        templates['vhdl'] = f
        break

    for f in verilog_templates:
      if os.path.exists(f):
        templates['verilog'] = f
        break

  return templates


def template_data_size(template_file):
  ''''Determine the data bus width used by an HDL template

  On Spartan-6 The Picoblaze-6 2K and 4K memories must be split across
  2Kx9 BRAMs and on Virtex-6 and 7-series the Picoblaze-6 4K memories
  must be split across 4Kx9 BRAMs.

  This scans a template file to see what format of init placeholder is
  used for address 00.
  '''
  with open(template_file, 'r') as fh:
    for l in fh:
      if '{[8:0]_INIT_00}' in l:
        return 9
      elif '{INIT_00}' in l:
        return 18

  return 18


import shutil

def get_templates():
  '''Create copies of standard templates from the installed package'''
  print('Retrieving default templates...')

  # Look relative to installed library
  try:
    lib_dir = os.path.dirname(sys.modules['opbasm_lib'].__file__)
    tpl_dir = os.path.normpath(os.path.join(lib_dir, '../templates'))
  except KeyError:
    # Look relative to this script
    tpl_dir = os.path.normpath(os.path.join(os.path.realpath(__file__), '../templates'))

  if not os.path.exists(tpl_dir):
    print('  No template directory found')
    sys.exit(1)

  files = os.listdir(tpl_dir)
  print(','.join(files))
  for f in files:
    p = os.path.join(tpl_dir, f)
    if not os.path.isfile(p): continue # Skip anything that isn't a file
    if os.path.isfile(f): continue # Skip files that already exist in the current directory

    print('  COPYING: ', p)
    shutil.copyfile(p, f)


def main():
  '''Main application code'''
  options = parse_command_line()


  if options.get_templates:
    get_templates()
    sys.exit(0)

  if options.hex_output:
    hex_mem_file = options.module_name + '.hex'
  else:
    hex_mem_file = options.module_name + '.mem'

  templates = find_templates(options.template_file)

  # Make sure the extension of the generated VHDL file matches the template extension
  if 'vhdl' in templates:
    vhdl_ext = os.path.splitext(templates['vhdl'])[1]
  else:
    vhdl_ext = '.vhdl'

  vhdl_file = options.module_name + vhdl_ext
  verilog_file = options.module_name + '.v'
  log_file = options.module_name + '.log'
  
  # Check for existence of input files
  if not os.path.exists(options.input_file):
    asm_error('Input file not found', exit=1)


  print(note('OPBASM - Open Picoblaze Assembler'))
  print(note('Running in ') + success('Picoblaze-{}'.format(6 if options.use_pb6 else 3)) + note(' mode'))

  print('  Device configuration:\n    Memory size: {}, Scratchpad size: {}\n'.format(\
    options.mem_size, options.scratch_size))

  timestamp = get_timestamp()
  upper_env_names = dict(((k.upper(), k) for k in os.environ.keys()))
  asm = Assembler(options.input_file, timestamp, options, upper_env_names)

  try:
    # Read input source
    for fname in asm.process_includes():
      print('  Reading source:', fname)

    # Assemble program
    print('\n  Assembling code... ', end='')
    sys.stdout.flush()

    assembled_code = asm.assemble()

  except FatalError, e:
    asm_error(*e.args, exit=1, statement=e.statement)

  print(success('SUCCESS'))

  # Print summary
  stats = code_stats(assembled_code)

  print('    {} instructions out of {} ({}%)'.format(stats['inst_count'], \
        options.mem_size, int(stats['inst_count'] / options.mem_size * 100)))
  print('    Highest occupied address: {:03X} hex'.format(stats['last_addr']))

  if len(templates) > 0:
    print('\n  Found template{}:'.format('s' if len(templates) > 1 else ''))
    for f in templates.values():
      print('   ', f)


  # Write results
  print('\n  Writing output')

  mmap = build_memmap(assembled_code, options.mem_size, asm.default_jump)
  write_hex_file(hex_mem_file, mmap)
  print('        mem map:', hex_mem_file)
  
  write_log_file(log_file, assembled_code, stats, asm, options.color_log)
  print('       log file:', log_file)


  minit_18 = build_xilinx_mem_init(mmap)
  minit_9 = build_xilinx_mem_init(mmap, split_data=True)

  if 'vhdl' in templates:
    data_size = template_data_size(templates['vhdl'])
    minit = minit_18 if data_size == 18 else minit_9

    write_hdl_file(options.input_file, vhdl_file, templates['vhdl'], minit, timestamp.isoformat())
    print('      VHDL file:', vhdl_file)

  if 'verilog' in templates:
    data_size = template_data_size(templates['verilog'])
    minit = minit_18 if data_size == 18 else minit_9

    write_hdl_file(options.input_file, verilog_file, templates['verilog'], minit, timestamp.isoformat())
    print('   Verilog file:', verilog_file)


  print('\n  Formatted source:')
  for fname, source in asm.sources.items():
    fname = os.path.splitext(os.path.basename(fname))[0] + '.fmt'
    print('   ', fname)
    with open(fname, 'w') as fh:
      for s in source:
        print(s.format(), file=fh)

  print('')


if __name__ == '__main__':
  main()
