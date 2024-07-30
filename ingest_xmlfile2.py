#!/usr/bin/env python3
# This is a cgi-bin script
# We read input XML from stdin, and write to the database
# See README and NOTES for general comments, particularly about XML processing

import re, sys, requests, json, time
import psycopg2
from urllib.parse import parse_qs
import html_utils

# Let's open the database connection right at the start;
# nothing else works if this is not good
conn = psycopg2.connect(database="museum", user="www-data");
cur = conn.cursor()

# CDATA makes XML hard to parse simplistically
# and is in any case a mere performance hack
# convert this to quoted text before processing
def sanitize_cdata(s: str) -> str:
   return re.sub(r"(?s)<CDATA\[\[(.*?)\]\]>", xml_quote, s)

# Get the objects out of the file, making very crude assumptions
# NOTE: XML should perhaps not be parsed like this in a production system
# this can break in several different ways, and will fail altogether
# if objects are nested
# also ignores a lot of little-used advanced XML features that are big security holes
# returns a list of tuples of (object, other)
# where 'object' is either a complete object or an empty string
# and 'other' is either a non-object text fragment or an empty string
def parse_fragments(tag_name: str, s: list):
   # Now having de-fanged the CDATA, parse for top-level objects
   # Note that this will fail if objects nest
   return re.findall(r"(?s)(<%s[^>]*>.*?</%s>)|([^<]*|<)" % (tag_name, tag_name), s, flags=re.DOTALL)

def normstr(s: str):
   return " ".join(s.split())

# TODO: handle failure in this; for example, if identifier is longer than the allowed 255 chars currently available
def insert_entry(identifier: str, filename: str, content: str):
   identifier = normstr(identifier)
   sys.stdout.write("INSERTING " + html_quote(identifier) + "<br>")
   sys.stdout.flush()
   # oh no, it's PL/SQL!
   # bit more complicated than a simple upsert
   cur.execute(
      """
BEGIN;
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
END;
COMMIT;
$$;""",
               (identifier,
                identifier, filename, content,
                content, filename, identifier, content,
                filename, identifier))

# carry this operation out on every object in the file
def process_file(filename: str, tag_name: str, s: str) -> str:
   n_items = 0
   missing_identifiers = 0
   for frag in parse_fragments(tag_name, s):
      object_text, other = frag
      if object_text:
         # HACK: definitely not how to parse XML!
         idf = re.findall(r"(?s)<ObjectIdentity>\s*<Number>\s*([^<>]+)\s*</Number>", object_text)
         if len(idf) == 1 and len(idf[0].strip()) > 0:
            insert_entry(idf[0].strip(), filename, object_text)
         else:
            missing_identifiers += 1
         n_items += 1
   return n_items, missing_identifiers

# NOTE: we only currently read the first file
def parse_multipart(s):
   lines = s.split('\n')
   end_separator = lines[0].rstrip() + "--"
   output = []
   skipping = 1
   filename = None
   for line in lines[1:]:
      if skipping:
         filename_match = re.findall(r'filename="([^"]*)"', line)
         if filename_match:
            filename = filename_match[0]
         if not line.strip():
            skipping = 0
         continue
      if line.rstrip() == end_separator:
         return ("\n".join(output), filename)
      output.append(line) 

def html_quote(s: str) -> str:
   s = str(s) 
   s = s.replace("&", "&amp;")
   s = s.replace("<", "&lt;")
   s = s.replace(">", "&gt;")
   s = s.replace('"', "&quot;")
   return s

def main():
   
   # don't forget the MIME type header!
   sys.stdout.write("Content-type: text/html; charset=utf-8\n\n")
   sys.stdout.write(html_utils.get_prelude())
   sys.stdout.flush()
   sys.stdout.write('<div class="browse-navbar">')
   sys.stdout.write('<h1>Ingesting XML file</h1>')
   sys.stdout.write('</div>')
   # read stdin all at once, will be available quickly
   object, filename = parse_multipart(sys.stdin.read())
   sys.stdout.write('<div class="scrollable-content">')
   n_items, missing_identifiers  = process_file(filename, "Object",  object)
   
   conn.commit()
   sys.stdout.write("File '%s' ingested, %d items processed, %d missing identifiers\n" % (html_quote(filename), n_items, missing_identifiers))
   sys.stdout.write('</div>')

   sys.stdout.write(html_utils.get_coda())

main()
