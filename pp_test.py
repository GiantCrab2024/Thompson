#!/usr/bin/env python3

# cut-down test of PostgreSQL access to try to debug concurrency issues

import re, sys, requests, json, time
import psycopg2

# Let's open the database connection right at the start;
# nothing else works if this is not good
conn = psycopg2.connect(database="museum", user="www-data");
cur = conn.cursor()


def say(*args):
   # use this if don't want to clutter up the systemd logs
   if 0:
      return
   print(*args, file=sys.stdout)
   sys.stdout.flush()

# assumes all the annotated objects are valid XML fragments
def process_entries():
   time.sleep(1)
   # look for entries where annotation is either nonexistent or stale
   cur.execute("""SELECT identifier, original_content FROM objects WHERE (annotated_updated IS NULL) OR (annotated_updated < original_updated) LIMIT 1;""", ())
   say("got", cur.rowcount, "rows")

def main():
   while 1:
      process_entries()

main()
