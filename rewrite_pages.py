import re

# transfer boilerplate from index page to other pages
# quick way of avoiding templating

managed_files = """
manage.html
export_xml.html
ingest_textfile.html
ingest_xmlfile.html
help.html
""".split()

source_file = open("index.html").read()
content_pattern = r'(?s)<!-- BEGIN CONTENT -->.*?<!-- END CONTENT -->'
prelude, coda = re.split(content_pattern, source_file)

# replace the prelude and coda in each managed file
# patches stuff in place, so don't forget to use git
for filename in managed_files:
    dest_file = open(filename).read()
    content = re.findall(content_pattern, dest_file)[0]
    updated_file = prelude + content + coda
    open(filename, "w").write(updated_file)
