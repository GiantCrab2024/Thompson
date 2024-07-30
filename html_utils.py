# this lets CGI pages style themselves to look like main page style
# you would normally use a web framework for this
import re

# this runs in the CGI environment, find the main page HTML there
source_file = open("../html/index.html").read()
content_pattern = r'(?s)<!-- BEGIN CONTENT -->.*?<!-- END CONTENT -->'
prelude, coda = re.split(content_pattern, source_file)

def get_prelude():
    return prelude

def get_coda():
    return coda
