from rdflib import Graph, Namespace
from rdflib.namespace import FOAF, RDF, RDFS, XSD

# Define your namespace prefixes
ol_ns = Namespace("http://edwh.nl/onze-leermiddelen/1.0#")

# Create your RDF graph
g = Graph()

# Define your classes
WorkExperience = ol_ns.WorkExperience
Attachment = ol_ns.Attachment
Organisation = ol_ns.Organisation

# Add your classes to the graph
g.add((WorkExperience, RDF.type, RDFS.Class))
g.add((Attachment, RDF.type, RDFS.Class))
g.add((Organisation, RDFS.type, RDFS.Class))
g.add((Organisation, RDFS.subClassOf, FOAF.Organization))

# Define your properties

# Rationale (Aanleiding) The term "rationale" refers to the reasoning or justification behind a particular teaching
# strategy, curriculum design, or educational activity. It encompasses the objectives and goals that educators aim to
# achieve through their instructional methods and materials. Outcomes (Resultaten) "Outcomes" in an educational
# context refer to the achievements or results that students attain as a consequence of their learning experiences.
# These can include knowledge gained, skills developed, attitudes changed, or behaviors modified as a result of
# educational activities. Methodology (Werkwijze) "Methodology" in education describes the systematic, theoretical
# analysis of the methods applied to a field of study. It includes the principles, theories, and practices that guide
# the design, implementation, and evaluation of educational programs and teaching strategies.

title = ol_ns.title
introduction = ol_ns.introduction
rationale = ol_ns.rationale
methodology = ol_ns.methodology
outcomes = ol_ns.outcomes
full_text = ol_ns.full_text

# Add your properties to the graph
g.add((title, RDF.type, RDF.Property))
g.add((title, RDFS.domain, WorkExperience))
g.add((title, RDFS.range, XSD.string))
g.add((title, RDFS.comment, RDF.Literal("In één regel kort en bondig waar de praktijk over gaat. De titel mag nooit beginnen met “de”, “het” of “een” of de naam van een school (probeer de schoolnaam te vermijden in de titel). Elke titel moet uniek zijn, als er een error komt zodra je de titel wilt opslaan is dit vaak omdat dezelfde titel al bestaat bij een andere praktijkervaring. Je kunt gebruikmaken van AI/ChatGPT voor het maken van meerdere verschillende titels die aan de bovenstaande regels voldoet.")))

g.add((rationale, RDF.type, RDF.Property))
g.add((rationale, RDFS.domain, WorkExperience))
g.add((rationale, RDFS.range, XSD.string))
g.add((rationale, RDFS.comment, RDF.Literal("Dit is de éérste zin van de praktijkervaring en wordt ook getoond op de kleinere kaartjes weergave voordat iemand op een praktijkervaring klikt. Deze wordt automatisch dik gedrukt op delen.meteddie.nl (dus dat hoeft niet binnen de editor te doen) en bestaat altijd uit 1 zin (dus met 1 punt). Eindig met een witregel.")))
g.add((rationale, RDFS.comment, RDF.Literal("School: let op, voornamelijk bij VO, of een school meerdere locaties heeft. Is dit zo? Schrijf er dan de locatie bij.")))
g.add((rationale, RDFS.comment, RDF.Literal("Datum: als er geen specifieke datum wordt genoemd, doe dan een schatting van het gestarte tijdstip. Wordt er geschreven start van (school)jaar X, vul dan in 1 september van dat schooljaar.")))


g.add((rationale, RDFS.comment, RDF.Literal("")))

g.add((outcomes, RDF.type, RDF.Property))
g.add((outcomes, RDFS.domain, WorkExperience))
g.add((outcomes, RDFS.range, XSD.string))
g.add((outcomes, RDFS.comment, RDF.Literal("")))

g.add((introduction, RDF.type, RDF.Property))
g.add((introduction, RDFS.domain, WorkExperience))
g.add((introduction, RDFS.range, XSD.string))
g.add((introduction, RDFS.comment, RDF.Literal("")))

g.add((full_text, RDF.type, RDF.Property))
g.add((full_text, RDFS.domain, WorkExperience))
g.add((full_text, RDFS.range, XSD.string))
g.add((full_text, RDFS., XSD.string))
g.add((full_text, RDFS.comment, RDF.Literal("Markdown content")))
g.add((full_text, RDFS.comment, RDF.Literal("Binnen dit schrijfvlak komt de lopende tekst van de praktijkervaring. Deze tekst bestaat uit de onderdelen die in dit hoofdstuk worden behandeld. Na de intro, een kopje of een paragraaf sluit je de tekst af met een witregel.")))

# Save your graph to a file
g.serialize("my_schema.rdf", format="xml")
g.serialize("my_schema.hext", format="hext")
g.serialize("my_schema.jsonld", format="jsonld")

buffer
g.serialize()
