#!/usr/bin/env python
"""
Copyright (C) 2012 Roman Lomonosov

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
 
THIS SOFTWARE IS PROVIDED BY AUTHOR AND CONTRIBUTORS ``AS IS'' AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED.  IN NO EVENT SHALL AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.
"""

VERSION = "1.4"

import inspect
import copy
import sys
import os

from google.protobuf import message as google_message

TYPE_HEADER_TEMPLATE = """
int ${message_type}__iter_unpack(const uint8_t* buffer, size_t buffer_size, uint8_t* memory, size_t memory_size);
int ${message_type}__iter_unpack_merge(${MessageType}* object, const uint8_t* buffer, size_t buffer_size, uint8_t* memory, size_t memory_size);
"""

MESSAGE_SOURCE_TEMPLATE = """
static ${MessageType} ${MessageType}__empty = ${MESSAGE_TYPE}__INIT;

int ${message_type}__iter_unpack_merge(${MessageType}* object, const uint8_t* buffer, size_t buffer_size, uint8_t* memory, size_t memory_size) {
  const uint8_t* buffer_end = buffer+buffer_size;
  const uint8_t* memory_end = memory+memory_size;
  ${additionally_variables}
  
  while (buffer < buffer_end) {
    ${switch_tree}
  }
  return memory_size-(memory_end-memory);
}

int ${message_type}__iter_unpack(const uint8_t* buffer, size_t buffer_size, uint8_t* memory, size_t memory_size) {
  const uint8_t* memory_end = memory+memory_size;
  ${MessageType} * object;
  
  if ( (object = (${MessageType}*)memory_allocate_copy(sizeof(${MessageType}),
                    &memory, memory_end,
                    (uint8_t*)&${MessageType}__empty, sizeof(${MessageType}))) == NULL) ERROR_MEMORY;

  int ret = ${message_type}__iter_unpack_merge(object, buffer, buffer_size, memory, memory_end-memory);
  if (ret >= 0) {
    return ret + sizeof(${MessageType});
  } else {
    return ret;
  }
}
"""

HEADER = """/* Generated by the protobuf-c-iter-unpack.py.  DO NOT EDIT! */

#ifndef PROTOBUF_ITER_RETURN
#define PROTOBUF_ITER_RETURN 1
#define PROTOBUF_ITER_WRONG_MESSAGE -1
#define PROTOBUF_ITER_NOT_ENOUGH_MEMORY -2
#endif

#ifndef PROTOBUF_FAST_${filename}__INCLUDED
#define PROTOBUF_FAST_${filename}__INCLUDED

${unpack_headers}

#endif  /* PROTOBUF_FAST_${filename}__INCLUDED */
"""

SOURCE = """/* Generated by the protobuf-c-iter-unpack.py.  DO NOT EDIT! */

#include <stdio.h>
#include <string.h>

#include "${filename}.pb-c.h"
#include "${filename}.pb-iter.h"

#define ERROR_UNPACK return PROTOBUF_ITER_WRONG_MESSAGE
#define ERROR_MEMORY return PROTOBUF_ITER_NOT_ENOUGH_MEMORY

static inline const uint8_t* memory_allocate(const size_t size,
                    uint8_t** memory, const uint8_t* memory_end) {
  if (memory_end < *memory + size) return NULL;
  *memory += size;
  return *memory - size;
}

static inline const uint8_t* memory_allocate_copy(const size_t size,
                    uint8_t** memory, const uint8_t* memory_end,
                    const uint8_t* src, const size_t src_size) {
  if (size < src_size) return NULL;
  if (memory_end < *memory + size) return NULL;
  if (*memory==src+src_size) { // resize if src is last allocated block
    *memory += size-src_size;
    return src;
  }
  memcpy(*memory, src, src_size);
  *memory += size;
  return *memory - size;
}

${readers}

static inline const uint8_t* skip_varint(const uint8_t* buffer, const uint8_t* buffer_end) {
  while (1) {
    if (buffer >= buffer_end) return NULL;
    if ((*buffer++)>>7==0) break;
  }
  return buffer;
}

static inline const uint8_t* skip_fixed32(const uint8_t* buffer, const uint8_t* buffer_end) {
  buffer+=4;
  if (buffer_end >= buffer)
    return buffer;
  return NULL;
}

static inline const uint8_t* skip_fixed64(const uint8_t* buffer, const uint8_t* buffer_end) {
  buffer+=8;
  if (buffer_end >= buffer)
    return buffer;
  return NULL;
}

static inline const uint8_t* skip_bytes(const uint8_t* buffer, const uint8_t* buffer_end) {
  uint32_t v = 0;
  if ((buffer = read_uint32(&v, buffer, buffer_end)) == NULL) return NULL;
  buffer += v;
  if (buffer_end >= buffer)
    return buffer;
  return NULL;
}

static inline const uint8_t* skip_field(const uint8_t* buffer, const uint8_t* buffer_end) {
  uint8_t type = (*buffer)&0x7;

  if ((buffer=skip_varint(buffer, buffer_end))==NULL) return NULL;

  switch (type) {
    case 0: //varint
      if ((buffer=skip_varint(buffer, buffer_end))==NULL) return NULL;
      break;
    case 1: //fixed64
      if ((buffer=skip_fixed64(buffer, buffer_end))==NULL) return NULL;
      break;
    case 2: //bytes
      if ((buffer=skip_bytes(buffer, buffer_end))==NULL) return NULL;
      break;
    case 5: //fixed32
      if ((buffer=skip_fixed32(buffer, buffer_end))==NULL) return NULL;
      break;
    default:
      return NULL;
      break;
  }
  return buffer;
}

${unpackers}

"""

LABEL_TO_NAME_MAP = {
  1: 'optional',
  2: 'required',
  3: 'repeated',
}

TYPE_ID_TO_NAME_MAP = { # type attribute (from google's _pb2.py file) to type name map
  1: 'double',
  2: 'float',
  3: 'int64',
  4: 'uint64',
  5: 'int32',
  6: 'fixed64',
  7: 'fixed32',
  8: 'bool',
  9: 'string',
  11: 'submessage',
  12: 'bytes',
  13: 'uint32',
  14: 'enum',
  15: 'sfixed32',
  16: 'sfixed64',
  17: 'sint32',
  18: 'sint64',
}

FIELD_TYPE_MAP = {} # maps field type name to wrapper class. filled by "field_type" decorator

#####################
# tempalates and helpers
#####################

def render_value(key, data):
  p = key.find(".")
  if p >= 0:
    subkey = key[p+1:]
    key = key[:p]
  else:
    subkey = None
  
  found = False
  value = None
  
  if not found:
    try:
      value = data[key]
      found = True
    except (KeyError,TypeError):
      pass
  
  if not found:
    try:
      value = data[int(key)]
      found = True
    except (KeyError,ValueError,IndexError):
      pass
  
  if not found:
    value = getattr(data, key, None)
    if not value is None:
      found = True
  
  if found:
    if callable(value):
      value = value()
  
  if not found:
    raise ValueError("key %s not found in %s" % (str(key), str(data)))

  if subkey:
    return render_value(subkey, value)
  return str(value)

def render(template,data):
  out = []
  for line in template.split("\n"):
    p1 = line.find("${")
    has_var = False
    while p1 >= 0:
      has_var = True
      p2 = line.find("}",p1)
      if p2 < 0: raise ValueError("Variable not closed: %s" % str([line,]))
      key = line[p1+2:p2]
      if line.strip() == ("${%s}" % key):
        t = []
        for l in render_value(key, data).split("\n"):
          t.append(line[:p1]+l)
        line = "\n".join(t)
      else:
        line = line[:p1]+render_value(key, data)+line[p2+1:]
      p1 = line.find("${")
    if has_var and not line.strip():
      continue
    out.append(line)
  out = "\n".join(out).split("\n")
  # fix intendation
  min_intendation = None
  for l in out:
    if not l.strip(): continue
    p = l.find(l.strip())
    if min_intendation is None or p < min_intendation:
      min_intendation = p
  if not min_intendation:
    return "\n".join(out)
  res = []
  for l in out:
    if not l.strip():
      res.append("")
      continue
    res.append(l[min_intendation:])
    
  # skip empty lines on start
  while res and not res[0].split():
    res = res[1:]
  # and at finish
  while res and not res[-1].split():
    res = res[:-1]
  return "\n".join(res)

def to_underlines(TypeName):
  """ TypeName -> type_name """
  type_name = ""
  for i,c in enumerate(TypeName):
    if c.lower() != c and c.upper() == c and i != 0 and TypeName[i-1].upper() != TypeName[i-1]:
      type_name += "_"
    type_name += c.lower()
  return type_name

#####################
# <fields>
#####################

def field(C):
  type_name = C.__name__[1:]
  if not type_name in TYPE_ID_TO_NAME_MAP.values():
    raise ValueError("unknown type %s" % type_name)
  if type_name in FIELD_TYPE_MAP:
    raise ValueError("field %s already implemented" % type_name)
  FIELD_TYPE_MAP[type_name] = C
  C.type_name = type_name
  return C

def get_field(protobuf_field):
  C = FIELD_TYPE_MAP[TYPE_ID_TO_NAME_MAP[protobuf_field.type]]
  return C(protobuf_field)

class _base(object):
  """
  @todo: Only repeated fields of primitive numeric types
  (types which use the varint, 32-bit, or 64-bit wire types) can be declared "packed".
  """
  repeated_init_size = 4
  
  def __init__(self, protobuf_field):
    self._field = protobuf_field

  def render(self, data):
    if isinstance(data, (list,)):
      return render("\n".join([s for s in data if s]),self)
    return render(data, self)
  
  def is_optional(self):
    return bool(LABEL_TO_NAME_MAP[self._field.label] == 'optional')
  
  def is_repeated(self):
    return bool(LABEL_TO_NAME_MAP[self._field.label] == 'repeated')
  
  def is_required(self):
    return bool(LABEL_TO_NAME_MAP[self._field.label] == 'required')
  
  def _tag(self, wire_type):
    b = []
    v = (self._field.number << 3) + wire_type
    while True:
      t = v & 0x7f
      v = v>>7
      if v > 0:
        b.append(t|0x80)
      else:
        b.append(t)
        break
    return b
  
  def tag(self):
    return self._tag(self.wire_type)

  def tag_packed(self):
    return self._tag(2)
  
  def is_packed(self):
    return self.is_repeated() and self.wire_type in (0,1,5)
  
  def cases(self):
    if self.is_packed():
      return [
        (self.tag(), self.read()),
        (self.tag_packed(), self.read_packed()),
      ]
    return [
        (self.tag(), self.read()),
    ]
  
  def name(self):
    return self._field.name.lower()
  
  def repeated_check_resize(self):
    if not self.is_repeated():
      return ""
    return self.render("""
      if ( ((object->n_${name}-1) & (object->n_${name})) == 0) {
        if (object->n_${name}==0) {
          if ((object->${name} = (${c_type}*)memory_allocate(${repeated_init_size}*sizeof(${c_type}), &memory, memory_end))==NULL) ERROR_MEMORY;
        } else if (object->n_${name} >= ${repeated_init_size}) {
          if ((object->${name} = (${c_type}*)memory_allocate_copy(2*(object->n_${name})*sizeof(${c_type}), &memory, memory_end, (uint8_t*)object->${name}, (object->n_${name})*sizeof(${c_type})))==NULL) ERROR_MEMORY;
        }
      }
    """)
  
  def repeated_increment_count(self):
    if not self.is_repeated():
      return ""
    return "object->n_${name}++;"
  
  def has_value_set_true(self):
    if self.is_optional():
      return "object->has_${name} = 1;"
    return ""
  
  def read_function(self):
    return "read_${type_name}"
  
  def read(self):
    if self.is_repeated():
      return self.render("""
        ${repeated_check_resize}
        if ((buffer=${read_function}(object->${name}+object->n_${name}, buffer, buffer_end))==NULL) ERROR_UNPACK;
        ${repeated_increment_count}
      """)
    return self.render("""
      if ((buffer=${read_function}(&(object->${name}), buffer, buffer_end))==NULL) ERROR_UNPACK;
      ${has_value_set_true}
    """)
  
  def read_packed(self):
    return self.render("""
      if ((buffer=read_int32(&t, buffer, buffer_end)) == NULL) ERROR_UNPACK;
      tmp_buffer_pointer = buffer+t;
      if (tmp_buffer_pointer > buffer_end) ERROR_UNPACK;
      while (buffer < tmp_buffer_pointer) {
        ${read}
      }
      if (buffer > tmp_buffer_pointer) ERROR_UNPACK;
    """)
  
class _varint(_base):
  wire_type = 0
  c_type = "uint64_t"
  tmp_type = "uint64_t"
  tmp_cast = "tmp"
  
  def reader(self):
    return self.render("""
      static inline const uint8_t* ${read_function}(void* v, const uint8_t* buffer, const uint8_t* buffer_end) {
        uint8_t i = 0;
        ${tmp_type} tmp = 0;
        while (1) {
          if (buffer>=buffer_end) return NULL;
          tmp |= ((${tmp_type})((*buffer)&0x7f))<<((i++)*7);
          if ((*buffer++)>>7) continue;
          break;
        }
        *(${c_type}*)v = ${tmp_cast};
        return buffer;
      }
    """)

@field
class _int32(_varint):
  c_type = "int32_t"
  tmp_cast = "(int32_t)tmp"

@field
class _uint32(_varint):
  c_type = "uint32_t"
  tmp_type = "uint32_t" #@todo: check speed

@field
class _sint32(_varint):
  c_type = "int32_t"
  tmp_type = "uint32_t" #@todo: check speed
  tmp_cast = "(int32_t)((tmp >> 1) ^ (-(tmp & 1)))"

@field
class _int64(_varint):
  c_type = "int64_t"
  tmp_cast = "(int64_t)tmp"

@field
class _uint64(_varint):
  c_type = "uint64_t"

@field
class _sint64(_varint):
  c_type = "int64_t"
  tmp_cast = "(int64_t)((tmp >> 1) ^ (-(tmp & 1)))"

@field
class _bool(_varint):
  c_type = "protobuf_c_boolean"
  tmp_cast = "(protobuf_c_boolean)tmp"

@field
class _enum(_varint):
  c_type = "uint32_t"

@field
class _fixed32(_base):
  wire_type = 5
  c_type = "uint32_t"
  
  def reader(self):
    return self.render("""
      #ifndef DECLARED_S_ENDIANLESS
      #define DECLARED_S_ENDIANLESS 1
      static const int s_endianness = 1;
      #endif
      
      static inline const uint8_t* ${read_function}(void* v, const uint8_t* buffer, const uint8_t* buffer_end) {
        if (buffer+4 > buffer_end) return NULL;
        if (1==*(char*)&(s_endianness)) { // runtime little-endian test 
          *(uint32_t*)v = *(uint32_t*)buffer;
        } else {
          *(uint32_t*)v = ((uint32_t)buffer[0]) | (((uint32_t)buffer[1]) << 8) \
             | (((uint32_t)buffer[2]) << 16) | (((uint32_t)buffer[3]) << 24);
        }
        return buffer+4;
      }
    """)

@field
class _sfixed32(_fixed32):
  c_type = "int32_t"
  read_function = "read_fixed32"

@field
class _float(_fixed32):
  c_type = "float"
  read_function = "read_fixed32"

@field
class _fixed64(_base):
  wire_type = 1
  c_type = "uint64_t"

  def reader(self):
    return self.render("""
      #ifndef DECLARED_S_ENDIANLESS
      #define DECLARED_S_ENDIANLESS 1
      static const int s_endianness = 1;
      #endif
      
      static inline const uint8_t* ${read_function}(void* v, const uint8_t* buffer, const uint8_t* buffer_end) {
        if (buffer+8 > buffer_end) return NULL;
        if (1==*(char*)&(s_endianness)) { // runtime little-endian test
          //memcpy((uint8_t*)v, buffer, 8);
          *(uint64_t*)v = *(uint64_t*)buffer;
          //*(uint32_t*)v = *(uint32_t*)buffer;
          //*(((uint32_t*)v)+1) = *(((uint32_t*)buffer)+1);
        } else {
          *(uint64_t*)v = ((uint64_t)buffer[0]) | (((uint64_t)buffer[1]) << 8) \
             | (((uint64_t)buffer[2]) << 16) | (((uint64_t)buffer[3]) << 24) \
             | (((uint64_t)buffer[4]) << 32) | (((uint64_t)buffer[5]) << 40) \
             | (((uint64_t)buffer[6]) << 48) | (((uint64_t)buffer[7]) << 56);
        }
        return buffer+8;
      }
    """)

@field
class _sfixed64(_fixed64):
  c_type = "int64_t"
  read_function = "read_fixed64"

@field
class _double(_fixed64):
  c_type = "double"
  read_function = "read_fixed64"

@field
class _string(_base):
  wire_type = 2
  c_type = "char*"

  def read_to_field(self):
    if self.is_repeated():
      return "*(object->${name}+object->n_${name})"
    else:
      return "object->${name}"

  def read(self):
    return self.render("""
      ${repeated_check_resize}
      if ((buffer=read_uint32(&length, buffer, buffer_end)) == NULL) ERROR_UNPACK;
      if (buffer + length > buffer_end) ERROR_UNPACK;
      if ((${read_to_field} = (char*)memory_allocate_copy(length+1,
          &memory, memory_end, buffer, length))==NULL) ERROR_MEMORY;
      *(memory-1) = 0;
      buffer += length;
      ${repeated_increment_count}
    """)

@field
class _submessage(_base):
  """
  @todo:For embedded message fields, the parser merges multiple instances
  of the same field, as if with the Message::MergeFrom method -
  that is, all singular scalar fields in the latter instance replace those in the former,
  singular embedded messages are merged, and repeated fields are concatenated.
  """
  wire_type = 2
  
  def submessage_type(self):
    return self._field.message_type.full_name.replace("_","").replace(".","__")
  
  def c_type(self):
    return "%s*" % self.submessage_type()
  
  def submessage_unpack(self):
    return to_underlines(self._field.message_type.full_name).lower().replace(".","__")+"__iter_unpack"

  def submessage_merge(self):
    return to_underlines(self._field.message_type.full_name).lower().replace(".","__")+"__iter_unpack_merge"
  
  def read_to_field(self):
    if self.is_repeated():
      return "*(object->${name}+object->n_${name})"
    else:
      return "object->${name}"
    
  def read(self):
    ret = """
        ${repeated_check_resize}
        if ((buffer=read_uint32(&length, buffer, buffer_end)) == NULL) ERROR_UNPACK;
        if (buffer + length > buffer_end) ERROR_UNPACK;
        buffer += length;
    """
    if self.is_repeated():
      ret+="""
        ${read_to_field} = (${submessage_type}*)memory;
        t = ${submessage_unpack}(buffer-length, length, memory, memory_end-memory);
      """
    else: # merge support
      ret+="""
        if (${read_to_field} == NULL) {
          ${read_to_field} = (${submessage_type}*)memory;
          t = ${submessage_unpack}(buffer-length, length, memory, memory_end-memory);
        } else {
          t = ${submessage_merge}(${read_to_field}, buffer-length, length, memory, memory_end-memory);
        }
      """
    
    ret+= """
        if (t < 0) return t;
        else memory += t;
        ${repeated_increment_count}
    """
    
    return self.render(ret)
      

@field
class _bytes(_base):
  wire_type = 2
  c_type = "ProtobufCBinaryData"

  def read_to_field(self):
    if self.is_repeated():
      return "(*(object->${name}+object->n_${name}))"
    else:
      return "object->${name}"

  def read(self):
    return self.render("""
      ${repeated_check_resize}
      if ((buffer=read_uint32(&(${read_to_field}.len), buffer, buffer_end)) == NULL) ERROR_UNPACK;
      if (buffer + ${read_to_field}.len > buffer_end) ERROR_UNPACK;
      if ((${read_to_field}.data = (uint8_t*)memory_allocate_copy(${read_to_field}.len,
          &memory, memory_end, buffer, ${read_to_field}.len))==NULL) ERROR_MEMORY;
      buffer += ${read_to_field}.len;
      ${repeated_increment_count}
      ${has_value_set_true}
    """)

#####################
# </fields>
#####################


class Message(object):
  def __init__(self, descriptor):
    self.descriptor = descriptor
    self.fields = []
    for num, field in descriptor.fields_by_number.items():
      self.fields.append(get_field(field))
      
  def render(self, msg):
    return render(msg, self)
    
  def generate_tree(self):
    tree = {}
    for i, field_info in enumerate(self.fields):
      for tag, read_source in field_info.cases():
        f = tree
        for b in tag[:-1]:
          if not b in f:
            f[b] = {}
          f = f[b]
        b = tag[-1]
        if not b in f:
          f[b] = read_source
    return tree
    
  def MessageType(self):
    return self.descriptor.full_name.replace("_","").replace(".","__")
  
  def message_type(self):
    return to_underlines(self.descriptor.full_name).lower().replace(".","__")
  
  def MESSAGE_TYPE(self):
    return to_underlines(self.descriptor.full_name).upper().replace(".","__")
  
  
  def is_has_repeated_fields(self):
    for f in self.fields:
      if f.is_repeated():
        return True
    return False
  
  def is_has_packed_fields(self):
    for f in self.fields:
      if f.is_packed():
        return True
    return False
  
  def is_has_field_type(self, types):
    for f in self.fields:
      if f.type_name in types:
        return True
    return False
  
  def additionally_variables(self):
    out = []
    if self.is_has_packed_fields():
      out.append("const uint8_t* tmp_buffer_pointer = NULL;")
    if self.is_has_packed_fields() or self.is_has_field_type(('submessage',)):
      out.append("int32_t t = 0;")
    if self.is_has_field_type(('string','submessage')):
      out.append("uint32_t length = 0;")
    return self.render("\n".join(out))
  
  def header(self):
    return self.render(TYPE_HEADER_TEMPLATE)
  
  def source(self):
    return self.render(MESSAGE_SOURCE_TEMPLATE)
  
  def readers(self):
    r = []
    for f in self.fields:
      try:
        r.append(f.reader())
      except AttributeError:
        pass
    return r
  
  def switch_tree(self, data=None, level=0):
    t = [
      "if (buffer + ${level} >= buffer_end) ERROR_UNPACK;" if level > 0 else "",
      "switch(buffer[${level}]) {",
      "  ${cases}",
      "  default:",
      "    if ((buffer=skip_field(buffer, buffer_end))==NULL) ERROR_UNPACK;",
      "    continue;",
      "}",
    ]
    
    t = "\n".join([s for s in t if s])
    
    if data is None:
      data = self.generate_tree()
    
    cases = []
    for byte, subdata in data.items():
      c = "\n".join([s for s in [
        "case ${byte}:",
        "  buffer += ${level+1};" if not isinstance(subdata,dict) else "",
        "  ${body}",
        "  continue;",
      ] if s])
      c_data = {'byte': hex(byte), 'level+1': level+1}
      if isinstance(subdata,dict):
        c_data['body'] = self.switch_tree(data=subdata, level=level+1)
      else:
        c_data['body'] = subdata
      cases.append(render(c, c_data))
    
    out = render(t, {'level':level, 'cases': "\n".join(cases)})
    return out
  
  
class Module(object):
  def __init__(self, module):
    self.messages = []
    self.module = module
    for k,v in module.__dict__.items():
      if not inspect.isclass(v):
        continue
      if not issubclass(v,google_message.Message):
        continue
      self.messages.append(Message(v.DESCRIPTOR))
      
    # nested messages
    i = 0
    while i < len(self.messages):
      j = i
      i = len(self.messages)
      for message in self.messages[j:i]:
        for submessage in message.descriptor.nested_types:
          self.messages.append(Message(submessage))
      
  def render(self, msg):
    return render(msg, self)
      
  def filename(self):
    return self.module.DESCRIPTOR.name.split(".")[0]
  
  def source_filename(self):
    return self.filename()+".pb-iter.c"
  
  def header_filename(self):
    return self.filename()+".pb-iter.h"
  
  def source(self):
    return self.render(SOURCE)
  
  def header(self):
    return self.render(HEADER)
  
  def readers(self):
    r = []
    for message in self.messages:
      r += message.readers()
    # hack for force add read_uint32
    r.append(_uint32(None).reader())
    r.append(_int32(None).reader())
    return "\n".join(sorted(list(set(r))))
  
  def unpackers(self):
    out = ""
    for message in self.messages:
      out += message.source()
    return out
  
  def unpack_headers(self):
    out = ""
    for message in self.messages:
      out += message.header()
    return out

def generate(filename):
  if not filename.endswith(".py"):
    print "Wrong python protobuf file: %s" % filename
    return
  module_name = filename[:-3]
  PROTO_DIR = os.path.abspath(os.path.dirname(filename))
  if not PROTO_DIR in sys.path: sys.path.insert(0, PROTO_DIR)

  module_imported = __import__(module_name, globals(), locals(), [], -1)
  
  module = Module(module_imported)

  f = open(os.path.join(PROTO_DIR,module.source_filename()),"w")
  f.write(module.source())
  f.close()
  
  f = open(os.path.join(PROTO_DIR,module.header_filename()),"w")
  f.write(module.header())
  f.close()

if __name__ == '__main__':
  for fn in sys.argv[1:]:
    generate(fn)

