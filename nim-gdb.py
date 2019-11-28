
import gdb
import re
import sys

# some feedback that the nim runtime support is loading, isn't a bad
# thing at all.
gdb.write("Loading Nim Runtime support.\n", gdb.STDERR)

# When error occure they occur regularly. This 'caches' known errors
# and prevents them from being reprinted over and over again.
errorSet = set()
def printErrorOnce(id, message):
  global errorSet
  if id not in errorSet:
    errorSet.add(id)
    gdb.write(message, gdb.STDERR)

nimobjfile = gdb.current_objfile() or gdb.objfiles()[0]
nimobjfile.type_printers = []

################################################################################
#####  Type pretty printers
################################################################################

type_hash_regex = re.compile("^\w*_([A-Za-z0-9]*)$")

def getNimRti(type_name):
  """ Return a ``gdb.Value`` object for the Nim Runtime Information of ``type_name``. """

  # Get static const TNimType variable. This should be available for
  # every non trivial Nim type.
  m = type_hash_regex.match(type_name)
  if m:
    try:
      return gdb.parse_and_eval("NTI_" + m.group(1) + "_")
    except:
      return None

class NimTypeRecognizer:
  # this type map maps from types that are generated in the C files to
  # how they are called in nim. To not mix up the name ``int`` from
  # system.nim with the name ``int`` that could still appear in
  # generated code, ``NI`` is mapped to ``system.int`` and not just
  # ``int``.

  type_map_static = {
    'NI': 'system.int',  'NI8': 'int8', 'NI16': 'int16',  'NI32': 'int32',  'NI64': 'int64',
    'NU': 'uint', 'NU8': 'uint8','NU16': 'uint16', 'NU32': 'uint32', 'NU64': 'uint64',
    'NF': 'float', 'NF32': 'float32', 'NF64': 'float64',
    'NIM_BOOL': 'bool', 'NIM_CHAR': 'char', 'NCSTRING': 'cstring',
    'NimStringDesc': 'string'
  }

  # Normally gdb distinguishes between the command `ptype` and
  # `whatis`.  `ptype` prints a very detailed view of the type, and
  # `whatis` a very brief representation of the type. I haven't
  # figured out a way to know from the type printer that is
  # implemented here how to know if a type printer should print the
  # short representation or the long representation.  As a hacky
  # workaround I just say I am not resposible for printing pointer
  # types (seq and string are exception as they are semantically
  # values).  this way the default type printer will handle pointer
  # types and dive into the members of that type.  So I can still
  # control with `ptype myval` and `ptype *myval` if I want to have
  # detail or not.  I this this method stinks but I could not figure
  # out a better solution.

  object_type_pattern = re.compile("^(\w*):ObjectType$")

  def recognize(self, type_obj):

    tname = None
    if type_obj.tag is not None:
      tname = type_obj.tag
    elif type_obj.name is not None:
      tname = type_obj.name

    # handle pointer types
    if not tname:
      if type_obj.code == gdb.TYPE_CODE_PTR:
        target_type = type_obj.target()
        target_type_name = target_type.name
        if target_type_name:
          # visualize 'string' as non pointer type (unpack pointer type).
          if target_type_name == "NimStringDesc":
            tname = target_type_name # could also just return 'string'
          # visualize 'seq[T]' as non pointer type.
          if target_type_name.find('tySequence_') == 0:
            tname = target_type_name

    if not tname:
      # We are not resposible for this type printing.
      # Basically this means we don't print pointer types.
      return None

    result = self.type_map_static.get(tname, None)
    if result:
      return result

    rti = getNimRti(tname)
    if rti:
      return rti['name'].string("utf-8", "ignore")
    else:
      return None

class NimTypePrinter:
  """Nim type printer. One printer for all Nim types."""


  # enabling and disabling of type printers can be done with the
  # following gdb commands:
  #
  #   enable  type-printer NimTypePrinter
  #   disable type-printer NimTypePrinter

  name = "NimTypePrinter"
  def __init__ (self):
    self.enabled = True

  def instantiate(self):
    return NimTypeRecognizer()


nimobjfile.type_printers = [NimTypePrinter()]

################################################################################
#####  GDB Function, equivalent of Nim's $ operator
################################################################################

class DollarPrintFunction (gdb.Function):
  "Nim's equivalent of $ operator as a gdb function, available in expressions `print $dollar(myvalue)"

  _gdb_dollar_functions = gdb.execute("info functions dollar__", True, True)
  dollar_functions = re.findall('NimStringDesc \*(dollar__[A-z0-9_]+?)\(([^,)]*)\);', _gdb_dollar_functions)

  def __init__ (self):
    super (DollarPrintFunction, self).__init__("dollar")

  @staticmethod
  def invoke_static(arg):

    for func, arg_typ in DollarPrintFunction.dollar_functions:

      if arg.type.name == arg_typ:
        func_value = gdb.lookup_global_symbol(func, gdb.SYMBOL_FUNCTIONS_DOMAIN).value()
        return func_value(arg)

      if arg.type.name + " *" == arg_typ:
        func_value = gdb.lookup_global_symbol(func, gdb.SYMBOL_FUNCTIONS_DOMAIN).value()
        return func_value(arg.address)

    typeName = arg.type.name
    printErrorOnce(typeName, "No suitable Nim $ operator found for type: " + typeName + ".\n")

  def invoke(self, arg):
    return self.invoke_static(arg)

DollarPrintFunction()

################################################################################
#####  GDB Command, equivalent of Nim's $ operator
################################################################################

class DollarPrintCmd (gdb.Command):
  """Dollar print command for Nim, `$ expr` will invoke Nim's $ operator"""

  def __init__ (self):
    super (DollarPrintCmd, self).__init__ ("$", gdb.COMMAND_DATA, gdb.COMPLETE_EXPRESSION)

  def invoke (self, arg, from_tty):
    param = gdb.parse_and_eval(arg)
    gdb.write(str(DollarPrintFunction.invoke_static(param)) + "\n", gdb.STDOUT)

DollarPrintCmd()

################################################################################
#####  Value pretty printers
################################################################################

class NimBoolPrinter:

  pattern = re.compile(r'^NIM_BOOL$')

  def __init__(self, val):
    self.val = val

  def to_string(self):
    if self.val == 0:
      return "false"
    else:
      return "true"

################################################################################

class NimStringPrinter:
  pattern = re.compile(r'^NimStringDesc \*$')

  def __init__(self, val):
    self.val = val

  def display_hint(self):
    return 'string'

  def to_string(self):
    if self.val:
      l = int(self.val['Sup']['len'])
      return self.val['data'][0].address.string("utf-8", "ignore", l)
    else:
     return ""

################################################################################

# proc reprEnum(e: int, typ: PNimType): string {.compilerRtl.} =
#   ## Return string representation for enumeration values
#   var n = typ.node
#   if ntfEnumHole notin typ.flags:
#     let o = e - n.sons[0].offset
#     if o >= 0 and o <% typ.node.len:
#       return $n.sons[o].name
#   else:
#     # ugh we need a slow linear search:
#     var s = n.sons
#     for i in 0 .. n.len-1:
#       if s[i].offset == e:
#         return $s[i].name
#   result = $e & " (invalid data!)"

def reprEnum(e, typ):
  """ this is a port of the nim runtime function `reprEnum` to python """
  e = int(e)
  n = typ["node"]
  flags = int(typ["flags"])
  # 1 << 2 is {ntfEnumHole}
  if ((1 << 2) & flags) == 0:
    o = e - int(n["sons"][0]["offset"])
    if o >= 0 and 0 < int(n["len"]):
      return n["sons"][o]["name"].string("utf-8", "ignore")
  else:
    # ugh we need a slow linear search:
    s = n["sons"]
    for i in range(0, int(n["len"])):
      if int(s[i]["offset"]) == e:
        return s[i]["name"].string("utf-8", "ignore")

  return str(e) + " (invalid data!)"

class NimEnumPrinter:
  pattern = re.compile(r'^tyEnum_(\w*)_([A-Za-z0-9]*)$')

  def __init__(self, val):
    self.val      = val
    match = self.pattern.match(self.val.type.name)
    self.typeNimName  = match.group(1)
    typeInfoName = "NTI_" + match.group(2) + "_"
    self.nti = gdb.lookup_global_symbol(typeInfoName)

    if self.nti is None:
      printErrorOnce(typeInfoName, "NimEnumPrinter: lookup global symbol '" + typeInfoName + " failed for " + self.val.type.name + ".\n")

  def to_string(self):
    if self.nti:
      arg0     = self.val
      arg1     = self.nti.value(gdb.newest_frame())
      return reprEnum(arg0, arg1)
    else:
      return self.typeNimName + "(" + str(int(self.val)) + ")"

################################################################################

class NimSetPrinter:
  ## the set printer is limited to sets that fit in an integer.  Other
  ## sets are compiled to `NU8 *` (ptr uint8) and are invisible to
  ## gdb (currently).
  pattern = re.compile(r'^tySet_tyEnum_(\w*)_([A-Za-z0-9]*)$')

  def __init__(self, val):
    self.val = val
    match = self.pattern.match(self.val.type.name)
    self.typeNimName  = match.group(1)

    typeInfoName = "NTI_" + match.group(2) + "_"
    self.nti = gdb.lookup_global_symbol(typeInfoName)

    if self.nti is None:
      printErrorOnce(typeInfoName, "NimSetPrinter: lookup global symbol '"+ typeInfoName +" failed for " + self.val.type.name + ".\n")

  def to_string(self):
    if self.nti:
      nti = self.nti.value(gdb.newest_frame())
      enumStrings = []
      val = int(self.val)
      i   = 0
      while val > 0:
        if (val & 1) == 1:
          enumStrings.append(reprEnum(i, nti))
        val = val >> 1
        i += 1

      return '{' + ', '.join(enumStrings) + '}'
    else:
      return str(int(self.val))

################################################################################

class NimHashSetPrinter:
  pattern = re.compile(r'^tyObject_(HashSet)_([A-Za-z0-9]*)$')

  def __init__(self, val):
    self.val = val

  def display_hint(self):
    return 'array'

  def to_string(self):
    counter  = 0
    capacity = 0
    if self.val:
      counter  = int(self.val['counter'])
      if self.val['data']:
        capacity = int(self.val['data']['Sup']['len'])

    return 'HashSet({0}, {1})'.format(counter, capacity)

  def children(self):
    if self.val:
      data = NimSeqPrinter(self.val['data'])
      for idxStr, entry in data.children():
        if int(entry['Field0']) > 0:
          yield ("data." + idxStr + ".Field1", str(entry['Field1']))

################################################################################

class NimSeqPrinter:
  # the pointer is explicity part of the type. So it is part of
  # ``pattern``.
  pattern = re.compile(r'^tySequence_\w* \*$')

  def __init__(self, val):
    self.val = val

  def display_hint(self):
    return 'array'

  def to_string(self):
    len = 0
    cap = 0
    if self.val:
      len = int(self.val['Sup']['len'])
      cap = int(self.val['Sup']['reserved'])

    return 'seq({0}, {1})'.format(len, cap)

  def children(self):
    if self.val:
      length = int(self.val['Sup']['len'])
      #align = len(str(length - 1))
      for i in range(length):
        yield ("data[{0}]".format(i), self.val["data"][i])

################################################################################

class NimArrayPrinter:
  pattern = re.compile(r'^tyArray_\w*$')

  def __init__(self, val):
    self.val = val

  def display_hint(self):
    return 'array'

  def to_string(self):
    return 'array'

  def children(self):
    length = self.val.type.sizeof // self.val[0].type.sizeof
    align = len(str(length-1))
    for i in range(length):
      yield ("[{0:>{1}}]".format(i, align), self.val[i])

################################################################################

class NimStringTablePrinter:
  pattern = re.compile(r'^tyObject_(StringTableObj)_([A-Za-z0-9]*)(:? \*)?$')

  def __init__(self, val):
    self.val = val

  def display_hint(self):
    return 'map'

  def to_string(self):
    counter  = 0
    capacity = 0
    if self.val:
      counter  = int(self.val['counter'])
      if self.val['data']:
        capacity = int(self.val['data']['Sup']['len'])

    return 'StringTableObj({0}, {1})'.format(counter, capacity)

  def children(self):
    if self.val:
      data = NimSeqPrinter(self.val['data'])
      for idxStr, entry in data.children():
        if int(entry['Field2']) > 0:
          yield (idxStr + ".Field0", entry['Field0'])
          yield (idxStr + ".Field1", entry['Field1'])

################################################################

class NimTablePrinter:
  pattern = re.compile(r'^tyObject_(Table)_([A-Za-z0-9]*)(:? \*)?$')

  def __init__(self, val):
    self.val = val
    # match = self.pattern.match(self.val.type.name)

  def display_hint(self):
    return 'map'

  def to_string(self):
    counter  = 0
    capacity = 0
    if self.val:
      counter  = int(self.val['counter'])
      if self.val['data']:
        capacity = int(self.val['data']['Sup']['len'])

    return 'Table({0}, {1})'.format(counter, capacity)

  def children(self):
    if self.val:
      data = NimSeqPrinter(self.val['data'])
      for idxStr, entry in data.children():
        if int(entry['Field0']) > 0:
          yield (idxStr + '.Field1', entry['Field1'])
          yield (idxStr + '.Field2', entry['Field2'])


################################################################

# this is untested, therefore disabled

# class NimObjectPrinter:
#   pattern = re.compile(r'^tyObject_.*$')

#   def __init__(self, val):
#     self.val = val

#   def display_hint(self):
#     return 'object'

#   def to_string(self):
#     return str(self.val.type)

#   def children(self):
#     if not self.val:
#       yield "object", "<nil>"
#       raise StopIteration

#     for (i, field) in enumerate(self.val.type.fields()):
#       if field.type.code == gdb.TYPE_CODE_UNION:
#         yield _union_field
#       else:
#         yield (field.name, self.val[field])

#   def _union_field(self, i, field):
#     rti = getNimRti(self.val.type.name)
#     if rti is None:
#       return (field.name, "UNION field can't be displayed without RTI")

#     node_sons = rti['node'].dereference()['sons']
#     prev_field = self.val.type.fields()[i - 1]

#     descriminant_node = None
#     for i in range(int(node['len'])):
#       son = node_sons[i].dereference()
#       if son['name'].string("utf-8", "ignore") == str(prev_field.name):
#         descriminant_node = son
#         break
#     if descriminant_node is None:
#       raise ValueError("Can't find union descriminant field in object RTI")

#     if descriminant_node is None: raise ValueError("Can't find union field in object RTI")
#     union_node = descriminant_node['sons'][int(self.val[prev_field])].dereference()
#     union_val = self.val[field]

#     for f1 in union_val.type.fields():
#       for f2 in union_val[f1].type.fields():
#         if str(f2.name) == union_node['name'].string("utf-8", "ignore"):
#            return (str(f2.name), union_val[f1][f2])

#     raise ValueError("RTI is absent or incomplete, can't find union definition in RTI")


################################################################################

def makematcher(klass):
  def matcher(val):
    typeName = str(val.type)
    try:
      if hasattr(klass, 'pattern') and hasattr(klass, '__name__'):
        # print(typeName + " <> " + klass.__name__)
        if klass.pattern.match(typeName):
          return klass(val)
    except Exception as e:
      print(klass)
      printErrorOnce(typeName, "No matcher for type '" + typeName + "': " + str(e) + "\n")
  return matcher

nimobjfile.pretty_printers = []
nimobjfile.pretty_printers.extend([makematcher(var) for var in list(vars().values()) if hasattr(var, 'pattern')])
