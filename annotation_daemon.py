#!/usr/bin/env python3

import re, sys, requests, json, time
from dotenv import dotenv_values
import psycopg2
import datetime

# Let's open the database connection right at the start;
# nothing else works if this is not good
conn = psycopg2.connect(database="museum", user="www-data");
cur = conn.cursor()

# secrets such as API keys are kept in the .env file -- LOCATION CURRENTLY HARDCODED
config = dotenv_values("/var/www/siliconprom/dotenv/.env")

def openai_api_call_core(query):
   headers = {"Content-Type": "application/json",
              "Authorization": "Bearer %s" % config["OPENAI_API_KEY"]}             
   url = config["OPENAI_API_URL"]
   req = requests.post(url, json=query, headers=headers)

   # not as expected? wait a bit, then quit
   # this avoids hammering the API endpoint on persistent errors
   # for example, running out of service credits
   # service runner should then restart the service
   if req.status_code != 200:
      print("HTTP status code != 200: value =", req.status_code, "text =", req.text)
      print("sleeping, then exiting")
      time.sleep(30)
      exit(1)

   return req.json()

def openai_api_call_aux(conversation_messages, temperature=0.2, n=1):
  response = openai_api_call_core(
  {    "model": "gpt-3.5-turbo",
       "temperature": temperature,
       "n": n,
      "messages": [
      {
        "role": "system",
        "content": "You are a museum cataloguer. You are careful, diligent and precise. You follow instructions very carefully, and think carefully before you answer questions."
      }] + conversation_messages
  })
  return response

def openai_api_call(conversation_messages, temperature=0.2):
   response = openai_api_call_aux(conversation_messages, temperature=0.2)
   return response["choices"][0]["message"]["content"]

def xml_quote(s: str) -> str:
   s = s.replace("&", "&amp;")
   s = s.replace("<", "&lt;")
   s = s.replace(">", "&gt;")
   s = s.replace('"', "&quot;")
   return s

# replace single with double backslashes
def bs_quote(s: str) -> str:
   return s.replace('\\', '\\\\')

long_description_prompt = {"role": "user",
"content": """
Describe the object described by the XML data given below.
Use complete sentences, not bullet points. Give full details of every part of the description.
Render dates formatted as day, month, year. (Example: "15.10.2013" should be rendered as "15 October 2013".
Where timestamps state the exact time-of-day, omit it in your output.
Where elements of the description are in superflous single or double quotes, and it will not change
the meaning, you should omit the quote characters.
Refer to the object described itself, not to the XML data.
Write your answer as clear, simple English prose.
Start your response with the words "This is".
Think carefully before you give your answer.
"""
}

short_description_prompt = {
   "role": "user", 
   "content": """
   Summarize the previous description in no more than 36 words.
   Write your answer as clear, simple, concise English prose.
   Start your summary with the indefinite article "A" or "An".
   Think carefully before you give your answer.
   """
}

categorization_prompt = {
   "role": "user", 
   "content": """
   Give a single noun or short noun phrase that best describes the object described by the XML data.
   Where possible, just use the simple noun form unless a noun phrase is clearer.
   Use a capital letter and the start and do not add quotes or put a full stop at the end.
   Do not use an adjectival form of a noun; use the base word..
   Always use the singular form of the noun.
   Output a word or words, not a symbol.
   Where something is a collection of items of the same type, use the term for that type.
   Where something is a collection of items of different types that fall under a more general class, use the term for that more general class.
   Try to avoid calling something just a "Collection", "Bundle"  or similar term, unless the items are too diverse to be categorized by a single term.
   If something is a container with a single more interesting object inside, refer to that object, not the container.
   Try not to call something a "Specimen" or "Object". Use a more precise descriptive term if possible.
   Where there is a choice between an abstract and concrete noun, choose the concrete one.
   Where it is not possible to make a meaningful decision, use the word 'Unknown'.
   IMPORTANT: Do not phrase your output as a sentence.
   IMPORTANT: Do not use the word "Collection" as the last word of your output.
   IMPORTANT: If there is a full stop at the end of the output, remove it.
   Think carefully before you give your answer.
   """
}

collections2_prompt = {
   "role": "user", 
   "content": """
   You are going to be asked to assign an object to a museum collection. You will be asked to give three choices,
   in descending order of certainty. You may use both the original XML document and the summary above for quidance.

   Collections are defined as follows:
   Each collection is defined as two lines: one with a number and name, the next with a natural language description of the objects that should be placed in that collection.
   The collection definitions follow, between the lines "BEGIN DESCRIPTIONS" and "END DESCRIPTIONS".
BEGIN DESCRIPTIONS
0. Architectural Plans Collection
Includes architectural plans of all descriptions.
1. Archaeology Collection
Includes artifacts, ecofacts, and documentation from past human activities, such as pottery, tools, bones, and field notes from archaeological excavations.
2. Art Collection
Comprises paintings, sculptures, prints, drawings, and other visual art forms, reflecting various artistic movements and periods.
3. Birds Eggs Collection
Contains preserved bird eggs, representing different species, used for the study of ornithology and bird breeding habits.
4. Ceramics Collection
Includes pottery, porcelain, and earthenware artifacts, often categorized by type, style, and period, such as vases, bowls, and tiles.
5. Conchology Collection
Features shells and shell-related artifacts, representing various mollusk species, used to study mollusk biology and diversity.
6. Dress Collection
Consists of clothing, accessories, and textiles from various cultures and time periods, illustrating fashion and social customs.
7. Egyptology Collection
Includes artifacts from ancient Egypt, such as mummies, hieroglyphic inscriptions, jewelry, and everyday objects, reflecting ancient Egyptian culture and history.
8. Entomology Collection
Contains preserved insect specimens, representing various species, used for the study of insect biology, behavior, and classification.
9. Ethnography (Non-European Social History) Collection
Comprises artifacts, clothing, tools, and documentation from non-European cultures, highlighting social practices, traditions, and daily life.
10. Geology Collection
Includes rocks, minerals, fossils, and geological samples, used to study the Earth's structure, history, and processes.
11. Herbaria Collection
Features preserved plant specimens, such as dried leaves, flowers, and seeds, used for botanical research and classification.
12. Lace & Tatting Collection
Contains samples of lace and tatting work, including doilies, trims, and garments, showcasing textile techniques and craftsmanship.
13. Lantern Slides Collection
Includes glass slides used in early projection devices, often featuring images of historical, educational, or cultural significance.
14. Library Collection
Comprises books, manuscripts, journals, and other printed materials, covering a wide range of subjects and serving as a resource for research and reference.
15. Local History Archives Collection
Contains documents, photographs, maps, and artifacts related to the history and development of a specific local area or community.
16. Militaria Collection
Includes military artifacts such as uniforms, weapons, medals, and equipment, reflecting military history and practices.
17. Natural History Collection
Features specimens from various branches of natural history, including zoology, botany, paleontology, and mineralogy, used for scientific study and education.
18. Numismatics Collection
Comprises coins, currency, tokens, and medals, offering insights into economic systems, trade, and historical chronology.
19. Oral History Collection
Includes recorded interviews, transcripts, and audio files of personal recollections and testimonies, preserving firsthand accounts of historical events and experiences.
20. Osteology Collection
Contains human and animal skeletal remains, used for the study of anatomy, health, and biological anthropology.
21. Photographs Collection
Features photographic prints, negatives, and digital images, documenting various subjects, events, and historical moments.
22. Postcards Collection
Includes postcards from different periods and locations, illustrating historical, cultural, and social aspects through images and messages.
23. Social History Collection
Comprises artifacts, documents, and ephemera related to everyday life and social practices, reflecting the lived experiences of various communities.
24. Taxidermy Collection
Contains mounted and preserved animal specimens, used for display, educational purposes, and the study of zoology.
25. Transport & Motor Racing Heritage Collection
Includes vehicles, racing memorabilia, photographs, and documentation related to the history of transport and motor racing, highlighting technological developments and cultural impact.   
END DESCRIPTIONS

   On the first line of your output, state which collection this object should be assigned to, giving only the collection's name, without the number, followed by a percentage confidence level.
   For example, if you are absolutely sure it is a photograph, the output should be "Photographs Collection 100%".
   Where multiple collections might be approriate, choose the most specific one.
   IMPORTANT: Pay particular attention to any original collection names given in the XML, and treat that as the most important information in making your choice.
   Give just the name of the collection.
   Do not put quotes around your answer.
   Do not put a full stop at the end of your answer.
   Do not invent collections that do not exist.
   Architectural plans SHOULD NOT be put in the Archeology Collection unless there is no other choice available.
   Postcards should always be put in the postcards collection.
   Insect specimens (eg. butterflies, bees, wasps) SHOULD NOT be put in the Natural History Collection.
   IMPORTANT: do not answer with a sentence.
   IMPORTANT: do not answer with anything other than the name of a collection that is in the list above followed by a percentage confidence figure..

   On the second line of your output, state your second-best choice of collection, on the same principles as above.

   On the third line of your output, state your third-best choice of collection, on the same principles as above.

   On the fourth, and final, line of your output, explain the reasons for how you made your choice of collection.

   Think carefully before you give your answers.  
   """
}

def normstr(s: str) -> str:
   return " ".join(s.split())

def annotate(tag_name: str, object_text: str) -> str:
   # remove any previous auto-annotation
   object_text = re.sub(r"(?s)<auto-annotation>.*</auto-annotation>", "", object_text)
   
   object_message = {
     "role": "user",
     "content": object_text
   }

   longdesc = openai_api_call([long_description_prompt , object_message])

   longdesc_message = {
     "role": "assistant",
     "content": longdesc
   }

   shortdesc = openai_api_call([long_description_prompt, object_message, longdesc_message, short_description_prompt])

   category = openai_api_call([long_description_prompt, object_message, longdesc_message, categorization_prompt])
   
   scratchpad = openai_api_call([long_description_prompt, object_message, longdesc_message, collections2_prompt])
   collection = re.findall(r"^(.*?) [0-9]+%\n", scratchpad)
   if not collection:
      collection = "**UNDEFINED**"
   else:
      collection = collection[0]
   
   return normstr(shortdesc), normstr(longdesc), normstr(category), normstr(collection), scratchpad

# object will already exist:
# TODO: handle failure in this; for example, if collection or category are longer than the allowed chars currently available
def update_entry(identifier: str, shortdesc: str, longdesc: str, category: str, collection: str, scratchpad: str):
   cur.execute("""UPDATE objects SET shortdesc=%s, longdesc=%s, category=%s, collection=%s, scratchpad=%s, annotated_updated = NOW() WHERE identifier = %s;""", (shortdesc, longdesc, category, collection, scratchpad, identifier))

def say(*args):
   # use this if don't want to clutter up the systemd logs
   if 0:
      return
   print(*args, file=sys.stdout)
   sys.stdout.flush()

# assumes all the annotated objects are valid XML fragments
def process_entries():
   time.sleep(2) # just a short delay between rounds, as belt-and-braces aganst API hammering

   # look for entries where annotation is either nonexistent or stale
   cur.execute("""SELECT identifier, original_content FROM objects WHERE (annotated_updated IS NULL) OR (annotated_updated < original_updated) LIMIT 1;""", ())
   say("got", cur.rowcount, "rows")
   conn.commit()

   # can only do one at a time, because of database concurrency issues, can't update mid-set of rows
   if cur.rowcount > 0:
      identifier, original_content = cur.fetchone()
      say("got entry", identifier)
      shortdesc, longdesc, category, collection, scratchpad = annotate("Object", original_content)
      say("annotated content", identifier)
      update_entry(identifier, shortdesc, longdesc, category, collection, scratchpad)
      say("updated entry", identifier)
      conn.commit()
   else:
      idle_seconds = 30
      say("idling for", idle_seconds, "seconds")
      time.sleep(idle_seconds)

def main():
   while 1:
      process_entries()

main()
