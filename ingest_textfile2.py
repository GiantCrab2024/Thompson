#!/usr/bin/env python3
# This is a cgi-bin script
# We read input XML from stdin, and write to the database
# See README and NOTES files for general comments

import re, sys, requests, json, time, os
import psycopg2
from urllib.parse import parse_qs
import datetime
from requests_toolbelt import MultipartDecoder
import html_utils

# Let's open the database connection right at the start;
# nothing else works if this is not good
conn = psycopg2.connect(database="museum", user="www-data");
cur = conn.cursor()

# Get the objects out of the file, making very crude assumptions
# NOTE: XML should perhaps not be parsed like this in a production system
# this can break in several different ways, and will fail altogether
# if objects are nested
# also ignores a lot of little-used advanced XML features that are big security holes
# returns a list of tuples of (object, other)
# where 'object' is either a complete object or an empty string
# and 'other' is either a non-object text fragment or an empty string

def normstr(s: str):
   return " ".join(s.split())

# TODO: handle failure in this; for example, if identifier is longer than
# the allowed 255 chars currently available
def insert_entry(identifier: str, filename: str, content: str):
   identifier = normstr(identifier)
   print("INSERTING", identifier)
   # oh no, it's PL/SQL!
   # bit more complicated than a simple upsert
   cur.execute(
      """
DO
$$
BEGIN
IF NOT EXISTS (SELECT FROM objects WHERE identifier = %s LIMIT 1)
   THEN
       INSERT INTO objects(identifier, original_filename, category, original_content, original_updated) VALUES (%s, %s, 'Uncategorized', %s, NOW());
   ELSE
      -- exists, check if it's changed as well
         UPDATE objects SET original_content = %s, original_filename = %s, category = 'Uncategorized', original_updated = NOW() WHERE identifier = %s AND NOT original_content = %s;
   END IF;
   -- set this even if the content hasn't changed
   UPDATE objects SET original_filename = %s WHERE identifier = %s;
END
$$;""",
               (identifier,
                identifier, filename, content,
                content, filename, identifier, content,
                filename, identifier))

def xml_quote(s: str) -> str:
   s = s.replace("&", "&amp;")
   s = s.replace("<", "&lt;")
   s = s.replace(">", "&gt;")
   s = s.replace('"', "&quot;")
   return s

# file is now only a single object, treat accordingly
def process_file(parameters: dict, tag_name: str, object_text: str) -> str:
   n_items = 0
   missing_identifiers = 0

   if object_text.strip():
      # fudge together some XML
      filename = parameters["filename"]
      timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d.%H.%M.%S")
      identifier = timestamp + " " + filename
      encoded_parms = ""
      for index in [1, 2, 3, 4, 5, 6]:
         name = normstr(parameters.get("param%s" % index))
         value = normstr(parameters.get("value%s" % index))
         # must be a valid XML entity name, we allow spaces, but will fix them
         # the string 'XML', in any casing, is reserved at the start of identifiers
         # ASCII-based tag names only
         if re.findall(r"^[_A-Za-z][-_\.A-Za-z0-9 ]*$", name) and name[:3].lower() != "xml":
            # spaces are not allowed in entities, fix these
            name = name.replace(' ', '-')
            encoded_parms += ("<%s>%s</%s>\n" %
                              (name, xml_quote(value), name))
      object_text = ("""<Object><identifier>%s</identifier>
<parameters>%s</parameters>
<object-description>%s</object-description>
</Object>""" %
                     (xml_quote(identifier), encoded_parms, xml_quote(object_text)))
      insert_entry(identifier, filename, object_text)
      n_items += 1

   return n_items, missing_identifiers

# parse whatever weird stuff Firefox gives us: needs more testing
def unmangle_entities(filename: str):
   return re.sub(r"&#([0-9]+);", lambda x: chr(int(x.group(1))), filename)

def parse_multipart(multipart_bytes: bytes, content_type: str):
   # assume for now everything is UTF-8 encoded
   # actually content-disposition headers are defined by RFC 6266,
   # with the filename encoded as per RFC 5987
   decoded = MultipartDecoder(multipart_bytes, content_type)
   parameters = {}
   content = ""
   for part in decoded.parts:
      content_disposition = part.headers[b'Content-Disposition'].decode("utf-8")
      filename_match = re.findall(r'filename="([^"]+)"', content_disposition)
      name_match = re.findall(r' name="([^"]+)"', content_disposition)
      if filename_match:
         parameters["filename"] = unmangle_entities(filename_match[0])
         content = part.content.decode("utf-8")
         continue
      if name_match:
         name = name_match[0]
         parameters[name] = part.content.decode("utf-8")
 
   return content, parameters

def html_quote(s: str) -> str:
   s = str(s) 
   s = s.replace("&", "&amp;")
   s = s.replace("<", "&lt;")
   s = s.replace(">", "&gt;")
   s = s.replace('"', "&quot;")
   return s

def main():
   content_type = os.environ.get("CONTENT_TYPE", "")
   
   # don't forget the MIME type header!
   sys.stdout.write("Content-type: text/html; charset=utf-8\n\n")
   # read stdin as byte string
   multipart_bytes = sys.stdin.buffer.read()
   content, parameters = parse_multipart(multipart_bytes, content_type)
   n_items, missing_identifiers = process_file(parameters, "Object",  content)
   filename = parameters["filename"]
   
   conn.commit()
   sys.stdout.write(html_utils.get_prelude())
   sys.stdout.write("File '%s' ingested, %d items processed, %d missing identifiers\n" % (html_quote(filename), n_items, missing_identifiers))
   sys.stdout.write(html_utils.get_coda())

main()
