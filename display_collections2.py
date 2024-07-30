#!/usr/bin/env python3
# This is a cgi-bin script
# See README and NOTES for general comments

import re, sys, requests, json, time, os
import psycopg2
from typing import TextIO
from urllib.parse import parse_qs, urlencode
import html_utils

# Let's open the database connection right at the start;
# nothing else works if this is not good
conn = psycopg2.connect(database="museum", user="www-data");
cur = conn.cursor()

   
def html_quote(s: str) -> str:
   s = s.replace("&", "&amp;")
   s = s.replace("<", "&lt;")
   s = s.replace(">", "&gt;")
   s = s.replace('"', "&quot;")
   return s

def display_collections_as_html(f: TextIO):
   cur.execute("SELECT collection, COUNT(*) FROM objects WHERE collection IS NOT NULL GROUP BY collection ORDER BY collection;")
   rowcount = cur.rowcount

   f.write('<div class="browse-navbar">')
   if rowcount > 0:
      f.write("Displaying %d collections<br>" % int(rowcount))
   else:
      f.write("No collections created yet<br>")
   f.write('</div>')
         
   f.write('<div class="scrollable-content">')
   f.write("<table><thead><tr><td>Collection</td><td>Count</td></tr></thead>\n")
   f.write("<tbody>\n")
   for e in cur:
      collection, count = e
      params = urlencode({"offset": 0, "limit": 20, "filter": collection})
      f.write("""
      <tr>
      <td><a href="/cgi/display_entries2.py?%s">%s</a></td>
      <td class="right-align">%d</td>
      </tr>\n""" % (params, html_quote(collection), count))
   f.write("</tbody>\n")
   f.write("</table>\n")
   f.write('</div>')

def parse_string(query: dict, param: str, default: int) -> int:
   items = query.get(param, [])
   if items:
      # normalize whitespace
      return " ".join(items[0].split())
   else:
      return default
   
def parse_number(query, param, default):
   s = parse_string(query, param, default)
   try:
      return int(s)
   except:
      return default

def main():
   # FOR POST
   # data = sys.stdin.readline()

   # FOR GET
   data = os.environ.get("QUERY_STRING", "")
   query = parse_qs(data)

   # don't forget the MIME type header!
   sys.stdout.write("Content-type: text/html; charset=utf-8\n\n")
   sys.stdout.write(html_utils.get_prelude())
   display_collections_as_html(sys.stdout)
   sys.stdout.write(html_utils.get_coda())
   conn.commit()

main()
