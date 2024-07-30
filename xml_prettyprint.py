import sys, re

# NOTE: this is prototyping code, not a proper XML processar 
# for production work, XML should be processed with a fully 
# conformant XML processor like defusedxml that protects
# against attacks that use obscure XML features:
# see https://docs.python.org/3/library/xml.html#defusedxml-package

# This errs on the side of safety at the cost of correctness

fragments = re.findall(r"<[^>]*>|[^<]*", sys.stdin.read())

indent = "   "
depth = 0
for frag in fragments:
   if frag[:1] == "<" and frag[:2] not in ["</", "<?"] and frag[-2:] != "/>":
        print(indent*depth + frag)
        depth += 1
   elif frag[:2] == "</":
        depth -= 1
        print(indent*depth + frag)
   else:
        print(indent*depth + frag)

