#!/usr/bin/env python3

# NOTE: this is prototyping code, not a proper XML processar 
# for production work, XML should be processed with a fully 
# conformant XML processor like defusedxml that protects
# against attacks that use obscure XML features:
# see https://docs.python.org/3/library/xml.html#defusedxml-package

import re, sys, requests, json, time, os
import psycopg2
from typing import TextIO
from urllib.parse import parse_qs, urlencode
import html_utils

# Let's open the database connection right at the start;
# nothing else works if this is not good
conn = psycopg2.connect(database="museum", user="www-data");
cur = conn.cursor()

# TODO: this is again somewhat heuristic code, use proper XML processor here instead
def xml_prettyprint(s: str) -> str:
   fragments = re.findall(r"<[^>]*>|[^<]*", s)
   output = []
   indent = "   "
   depth = 0
   for frag in fragments:
      if frag[:1] == "<" and frag[:2] not in ["</", "<?"] and frag[-2:] != "/>":
           output.append(indent*depth + frag)
           depth += 1
      elif frag[:2] == "</":
           depth -= 1
           output.append(indent*depth + frag)
      else:
           if frag.strip():
              output.append(indent*depth + frag.strip())
   output = "\n".join(output)

   # peephole optimise one-liners with single, simple,  strings
   return re.sub(r"(?s)(<[^/>][^<>/]*>)\s*([^<>\n]{,20})\s*(</[^<>/]+>)", r"\1 \2 \3", output)
   
def html_quote(s: str) -> str:
   s = str(s) 
   s = s.replace("&", "&amp;")
   s = s.replace("<", "&lt;")
   s = s.replace(">", "&gt;")
   s = s.replace('"', "&quot;")
   return s

# assumes input already HTML-escaped
def textarea(label: str, content: str, rows=1) -> str:
   return '%s:<br><textarea readonly rows="%d">%s</textarea>' % (label, rows, content) 

def linked_word(s: str, fresh):
   return '<a href="/cgi/display_entries2.py?%s">%s</a>' % (urlencode({"filter": s, "fresh": fresh}), html_quote(s))

def navbar(f, offset, limit, rowcount, total_count, filterstring, fresh, freetext):
   if filterstring:
      if freetext:
          htmlcat = "free text search '%s'" % html_quote(filterstring)
      else:
          htmlcat = "exact label match '%s'" % html_quote(filterstring)
   else:
      htmlcat = "all categories"

   if fresh:
      htmlcat += ", fresh entries only"

   f.write('<div class="browse-navbar">')

   if rowcount > 0:
      f.write("Displaying entries %d to %d of %d for %s<br>" % (offset+1, offset+rowcount, total_count, htmlcat))
   else:
      if limit > 0:
         f.write("No more entries for %s<br>" % htmlcat)
      else:
         f.write("No entries found for %s<br>" % htmlcat)

   f.write('<a href="/cgi/display_entries2.py?%s">&lt; Previous %d entries</a> | ' %
           (urlencode({"offset": max(0, offset-limit), "limit": limit, "filter": filterstring}), limit))
   f.write('<a href="/cgi/display_entries2.py?%s">Next %d entries &gt</a> | ' %
           (urlencode({"offset": offset+limit, "limit": limit, "filter": filterstring}), limit))
   
   f.write('<a href="/cgi/display_categories2.py">Categories</a> | ')   
   f.write('<a href="/cgi/display_collections2.py">Collections</a> | ')   
   f.write('<a href="/cgi/display_filenames2.py">Filenames</a>')   
   f.write('<hr>')
   f.write('</div>')

def normstr(s: str):
   return " ".join(s.split())

# we don't want anything with even a chance of being a Postgres special character
# note that isalnum() works for all Unicode characters now eg. accented letters
def goodchar(c: str):
   if c.isalnum():
      return c
   # otherwise
   return ' '

# unlike with the input code, assume output may be too big just to pull into RAM at one go
# assumes all the annotated objects are valid XML fragments
def display_entries_as_html(f: TextIO, limit, offset, filterstring, fresh):
   args = []

   # Normalise, checking for the magic word "find"
   filterstring = filterstring.split()
   freetext = filterstring and filterstring[0].lower() == "find"
   if freetext:
      filterstring = filterstring[1:]
   filterstring = " ".join(filterstring)

   # TODO: audit this entire things for safety against SQL injection
   if freetext:   
      # belt and braces over and above psycopg quoting - just white out any potentially nasty characters
      filterstring = normstr("".join([goodchar(c) for c in filterstring]))

   query = "SELECT COUNT(*) FROM objects WHERE annotated_updated IS NOT NULL"
   if filterstring and not freetext:
      query += "  AND (identifier = %s OR category = %s OR collection = %s OR original_filename = %s)"
      args += [filterstring, filterstring, filterstring, filterstring]
   if filterstring and freetext:
      query += " AND (longdesc @@ websearch_to_tsquery(%s))"
      args += [filterstring]
   if fresh:
      query += " AND annotated_updated >= original_updated"  
   query += ";"
   cur.execute(query, tuple(args))
      
   total_count = int(cur.fetchone()[0])

   args = []
   query = "SELECT ROW_NUMBER() OVER (ORDER BY identifier), identifier, original_filename, category, collection, original_content, shortdesc, longdesc, scratchpad FROM objects WHERE annotated_updated IS NOT NULL"
   if filterstring and not freetext:
      query += "  AND (identifier = %s OR category = %s OR collection = %s OR original_filename = %s)"
      args += [filterstring, filterstring, filterstring, filterstring]
   if filterstring and freetext:
      query += " AND (longdesc @@ websearch_to_tsquery(%s))"
      args += [filterstring]
   if fresh:
      query += " AND annotated_updated >= original_updated"  
   query += " ORDER BY identifier LIMIT %s OFFSET %s;"
   args += [limit, offset]   
   cur.execute(query, tuple(args))
      
   rowcount = cur.rowcount

   navbar(f, offset, limit, rowcount, total_count, filterstring, fresh, freetext)

   f.write('<div class="scrollable-content">')
   for e in cur:
      row, identifier, original_filename, category, collection, original_xml, shortdesc, longdesc, scratchpad = e

      original_collection = ", ".join(list(['"%s"' % normstr(x) for x in re.findall("(?s)<CollectionName>([^<>]*)</CollectionName>", original_xml)]))
      
      f.write("Entry %d of %d" % (row, total_count))
      f.write("<table>")
      f.write("<tr><td>Identifier:</td><td>" + linked_word(str(identifier), fresh) + "</td></tr>")
      f.write("<tr><td>Category:</td><td>" + linked_word(str(category), fresh) + "</td></tr>")
      f.write("<tr><td>Collection:</td><td>" + linked_word(str(collection), fresh) + "</td></tr>")
      f.write("<tr><td>Original filename:</td><td>" + linked_word(str(original_filename), fresh) + "</td></tr>")
      f.write("<tr><td>Original collection names:</td><td>" + html_quote(original_collection))
      f.write("</table>")
      
      f.write(textarea("Prettyprinted original XML", html_quote(xml_prettyprint(original_xml)), rows=10))
      f.write("<br>")
      f.write(textarea("Short description", html_quote(shortdesc,), rows=3))
      f.write("<br>")
      f.write(textarea("Long description", html_quote(longdesc), rows=10))
      f.write("<br>")
      f.write(textarea("Scratchpad", html_quote(scratchpad), rows=5))
      f.write("<hr>\n")
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

# parse whatever weird stuff Firefox gives us in HTTP POST data: needs more testing                                                 
def unmangle_entities(filename: str):
   return re.sub(r"&#([0-9]+);", lambda x: chr(int(x.group(1))), filename)
   
def main():
   # FOR POST
   # data = sys.stdin.readline()

   # FOR GET
   data = os.environ.get("QUERY_STRING", "")
   query = parse_qs(data)

   # don't forget the MIME type header!
   sys.stdout.write("Content-type: text/html; charset=utf-8\n\n")
   
   # parse, clamping negative values to zero
   limit = max(0, parse_number(query, "limit", 20))
   offset = max(0, parse_number(query, "offset", 0))
   filterstring = unmangle_entities(parse_string(query, "filter", ""))
   fresh = parse_string(query, "fresh", "")

   sys.stdout.write(html_utils.get_prelude())
   display_entries_as_html(sys.stdout, limit, offset, filterstring, fresh)
   sys.stdout.write(html_utils.get_coda())
   conn.commit()

main()
