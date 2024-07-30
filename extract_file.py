#!/usr/bin/env python3
# This is a cgi-bin script
# See README and NOTES for general comments

import re, sys, requests, json, time, datetime
import psycopg2
from typing import TextIO

# Let's open the database connection right at the start;
# nothing else works if this is not good
conn = psycopg2.connect(database="museum", user="www-data");
cur = conn.cursor()

def xml_quote(s: str) -> str:
   s = s.replace("&", "&amp;")
   s = s.replace("<", "&lt;")
   s = s.replace(">", "&gt;")
   s = s.replace('"', "&quot;")
   return s

# replace single with double backslashes
def bs_quote(s: str) -> str:
   return s.replace('\\', '\\\\')

# TODO: this is a bit ugly, do with proper XML handling code, probably should insert on output, not here
def insert_annotation(tag_name: str, object_text: str, shortdesc: str, longdesc: str, timestamp: str, category: str, collection: str, original_filename: str):
   # remove any previous auto-annotation
   object_text = re.sub(r"(?s)<auto-annotation>.*</auto-annotation>", "", object_text)

   # note that the substitution strings need to be backslash-escaped to prevent blowing up re.sub
   return re.sub("</%s>$" % tag_name, 
     """
     <auto-annotation>
     <shortdesc>\n%s\n</shortdesc>
     <longdesc>\n%s\n</longdesc>
     <category>%s</category>
     <collection>%s</collection>
     <original_filename>%s</original_filename>
     <updated>%s</updated>
     </auto-annotation>\\g<0>
     """ % 
         (bs_quote(xml_quote(shortdesc)),
          bs_quote(xml_quote(longdesc)),
          bs_quote(xml_quote(category)),
          bs_quote(xml_quote(collection)),
          bs_quote(xml_quote(original_filename)),
          bs_quote(xml_quote(timestamp.replace(microsecond=0).isoformat()))
          ),
                 object_text)

# unlike with the input code, assume output may be too big just to pull into RAM at one go
# assumes all the annotated objects are valid XML fragments
def extract_entries_to_file(f: TextIO):
   cur.execute("""SELECT original_content, original_filename, category, collection, shortdesc, longdesc, annotated_updated FROM objects WHERE annotated_updated IS NOT NULL;""", ())

   f.write("<Interchange>")
   for e in cur:
      original_content, original_filename, category, collection, shortdesc, longdesc, annotated_updated = e
      annotated_content = insert_annotation("Object", original_content, shortdesc, longdesc, annotated_updated, category, collection, original_filename)
      f.write(annotated_content)
   f.write("</Interchange>")

def main():
   # don't forget the MIME type header!
   sys.stdout.write("Content-type: application/xml\n\n")
   extract_entries_to_file(sys.stdout)
   conn.commit()

main()
