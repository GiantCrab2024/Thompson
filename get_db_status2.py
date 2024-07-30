#!/usr/bin/env python3
# This is a cgi-bin script
# See README and NOTES for general comments

import re, sys, requests, json
from dotenv import dotenv_values
import psycopg2
import html_utils

# Let's open the database connection right at the start;
# nothing else works if this is not good
conn = psycopg2.connect(database="museum", user="www-data");
cur = conn.cursor()

def say(*args):
   print(*args, file=sys.stdout)
   sys.stdout.flush()

# unlike with the input code, assume output may be too big just to pull into RAM at one go
# assumes all the annotated objects are valid XML fragment
def get_db_status():
   say('<div class="browse-navbar">')
   say('<h1>System status</h1>')
   say('</div>')
   say('<div class="scrollable-content">')
   say("<table>")
   # look for entries where annotation is either nonexistent or stale
   cur.execute("""SELECT COUNT(*) FROM objects;""", ())
   say('<tr><td class="right-align">', cur.fetchone()[0], "</td><td>total objects</td></tr>")
   cur.execute("""SELECT COUNT(*) FROM objects WHERE (annotated_updated IS NOT NULL);""", ())
   say('<tr><td class="right-align">', cur.fetchone()[0], "</td><td>total annotations</td></tr>")
   cur.execute("""SELECT COUNT(*) FROM objects WHERE (annotated_updated IS NULL);""", ())
   say('<tr><td class="right-align">', cur.fetchone()[0], "</td><td>missing annotations</td></tr>")
   cur.execute("""SELECT COUNT(*) FROM objects WHERE (annotated_updated < original_updated);""", ())
   say('<tr><td class="right-align">', cur.fetchone()[0], "</td><td>stale annotations</td></tr>")
   cur.execute("""SELECT COUNT(*) FROM objects WHERE (annotated_updated IS NOT NULL) AND (annotated_updated >= original_updated);""", ())
   say('<tr><td class="right-align">', cur.fetchone()[0], "</td><td>fresh annotations</td></tr>")
   cur.execute("""SELECT COUNT(*) FROM objects WHERE (annotated_updated IS NULL) OR (annotated_updated < original_updated);""", ())
   say('<tr><td class="right-align">', cur.fetchone()[0], "</td><td>pending annotations</td></tr>")
   say("</table>")
   say("</div>")


def main():

   sys.stdout.write("Content-type: text/html\n\n")
   sys.stdout.write(html_utils.get_prelude())
   get_db_status()
   sys.stdout.write(html_utils.get_coda())

main()
