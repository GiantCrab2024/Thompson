#!/usr/bin/env python3
# This is a cgi-bin script
# See README and NOTES for general comments

import re, sys, requests, json, time
import psycopg2
from urllib.parse import parse_qs
import html_utils

# Let's open the database connection right at the start;
# nothing else works if this is not good
conn = psycopg2.connect(database="museum", user="www-data");
cur = conn.cursor()

def execute_with_filterstring(cur, query, filterstring):
   if not filterstring:
      sys.stdout.write('please specify either a filter, or the words "ENTIRE DATABASE"\n')
      return
   
   if filterstring == "ENTIRE DATABASE":
      query += ";"
      cur.execute(query, ())
   else:
      query += """ WHERE (category = %s OR collection = %s OR identifier = %s OR original_filename = %s);"""
      cur.execute(query, (filterstring, filterstring, filterstring, filterstring))

   sys.stdout.write('\n')

# parse whatever weird stuff Firefox gives us: needs more testing
def unmangle_entities(filename: str):
   return re.sub(r"&#([0-9]+);", lambda x: chr(int(x.group(1))), filename)
   
def main():
   # FOR POST
   data = sys.stdin.readline()
   query = parse_qs(data)

   delete_annotations = query.get("delete_annotations") == ['y']
   delete_original = query.get("delete_original") == ['y']
   touch = query.get("touch") == ['y']
   confirmed = query.get("confirmed") == ['y']
   filterstring = unmangle_entities(query.get("filter", [''])[0])

   # don't forget the MIME type header!
   sys.stdout.write("Content-type: text/html; charset=utf-8\n\n")
   sys.stdout.write(html_utils.get_prelude())

   if not filterstring:
      sys.stdout.write("You didn't specify what to delete.\n")
      sys.stdout.write('Please specify either a filter, or the words "ENTIRE DATABASE" if you really mean that.\n')
      sys.stdout.write(html_utils.get_coda())
      exit(0)

   if not confirmed:
      sys.stdout.write("Request not confirmed, skipping.\n")
      sys.stdout.write(html_utils.get_coda())
      exit(0)

   if touch:
      query ="""UPDATE objects SET original_updated=NOW() """
      sys.stdout.write("Marking specified objects in database for refresh.\n")
      execute_with_filterstring(cur, query, filterstring)

   if delete_original:
      query = """DELETE FROM objects """
      sys.stdout.write("Deleting specified entries in database.\n")
      execute_with_filterstring(cur, query, filterstring)

   if delete_annotations:
      query = """UPDATE objects SET annotated_updated = NULL, shortdesc = NULL, longdesc = NULL, category = NULL, collection = NULL, scratchpad = NULL """
      sys.stdout.write("Deleting specified annotations in database.\n")
      execute_with_filterstring(cur, query, filterstring)

   sys.stdout.write(html_utils.get_coda())

   conn.commit()

main()
