CGI_DIR=/var/www/siliconprom/cgi-bin/
HTML_DIR=/var/www/siliconprom/html/ 
DAEMON_DIR=/var/www/siliconprom/daemon/

# get rid of obsolete files
rm $CGI_DIR/*.py
rm $HTML_DIR/*.html

# Background daemon
cp annotation_daemon.py $DAEMON_DIR

# backwards compatibility with old location
cp index2.html $HTML_DIR

# new UI
cp index.html $HTML_DIR
cp html_utils.py $CGI_DIR
cp display_entries2.py $CGI_DIR
cp manage_entries2.py $CGI_DIR
cp display_filenames2.py $CGI_DIR
cp display_categories2.py $CGI_DIR
cp display_collections2.py $CGI_DIR
cp ingest_textfile2.py $CGI_DIR
cp ingest_xmlfile2.py $CGI_DIR
cp get_db_status2.py $CGI_DIR
cp manage.html $HTML_DIR
cp help.html $HTML_DIR
cp extract_file.py  $CGI_DIR
# cp index2.html $HTML_DIR
cp ingest_xmlfile.html ingest_textfile.html $HTML_DIR
cp export_xml.html $HTML_DIR
cp style.css magnify.svg $HTML_DIR
cp 'Museum_Logo_new_square - thumb.png' $HTML_DIR

# kick nginx to reload state
systemctl reload nginx

# setup the background process
cp database_annotator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart database_annotator.service


