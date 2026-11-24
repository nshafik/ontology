# Philosophy ontology - SPARQL query collection (CQ1-CQ15)

Owner: Person 1 (Ontology & Knowledge Graph). Matches the 15 competency questions in Section 3 of the design brief.

**How to run.** Load `philosophy_ontology.ttl` and `philosophy_dataset.ttl` into one dataset (Fuseki / GraphDB), or open `philosophy_complete.ttl` in Protégé and use the SPARQL Query tab. Every query uses property paths (`:studiedUnder+`, `:subSchoolOf+`) and does **not** need the reasoner, so results are identical with or without inference. Where a reasoned variant exists (`:hasTeachingAncestor`, `:CriticizedWork`, `:isWithinSchool`) it is shown as a comment.

Do **not** load `philosophy_links.ttl` into the same graph when running these queries. Its `owl:sameAs` statements make each philosopher, its Wikidata item and its DBpedia resource the same individual, so under inference every result row is returned once per coreferent IRI (`:StudentThinker` reports 33 members instead of 11). Keep the links in a separate named graph.

**Status: executed and verified.** Every query below has been run on a real SPARQL engine (RDFLib 7.6.0) against `philosophy_ontology.ttl` + `philosophy_dataset.ttl`, and every result matches its Expected table. The checks are automated in `build.py` (step 6), which asserts the exact row count of each query and fails the build on any drift:

```
$ python3 build.py
[6] Competency questions
  ok   CQ1  ... CQ15, R1, R2        19/19 checks passed
  SHACL PASS | HermiT PASS | OWL-RL PASS | Queries PASS
```

Reasoning was additionally verified with **HermiT** (via owlready2, step 4: consistent, 0 unsatisfiable classes) and an **OWL-RL** closure (step 5: 1,301 → 3,490 triples). Last run: 2026-11-21.

Where a question names a specific work, philosopher or reader, the parameter is set with `VALUES` or `FILTER` so you can swap it.

## CQ1. Author and school of a book
**Question:** Which author does the book belong to, and which school does the author belong to?  
**SPARQL features:** SELECT, FILTER  
**Ontology evidence path:** `:Work -createdBy-> :Philosopher -belongsToSchool-> :SchoolOfThought`

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT ?bookTitle ?authorName ?school
WHERE {
  ?book :title ?bookTitle ; :createdBy ?author .
  ?author rdfs:label ?authorName .
  OPTIONAL { ?author :belongsToSchool ?s . ?s rdfs:label ?school }
  FILTER (?book = :CritiquePureReason)
}
```

*Note:* OPTIONAL keeps authors with no recorded school (e.g. Schopenhauer, Arendt, Gadamer, Mill, Marx, Nietzsche).

**Expected result**

| bookTitle | authorName | school |
|---|---|---|
| Critique of Pure Reason | Immanuel Kant | German idealism |


## CQ2. Teachers, directly and indirectly
**Question:** Which philosophers studied under other philosophers, directly and not directly?  
**SPARQL features:** SELECT, UNION, property path  
**Ontology evidence path:** `:Philosopher -studiedUnder+-> :Philosopher` (reasoner: `:hasTeachingAncestor`, the transitive super-property)

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT ?studentName ?teacherName ?link
WHERE {
  { ?s :studiedUnder ?t .                     BIND("direct"   AS ?link) }
  UNION
  { ?s :studiedUnder/:studiedUnder+ ?t .      BIND("indirect" AS ?link) }
  ?s rdfs:label ?studentName .
  ?t rdfs:label ?teacherName .
}
ORDER BY ?link ?studentName ?teacherName
# Reasoned variant: SELECT ?s ?t WHERE { ?s :hasTeachingAncestor ?t }
```

**Expected result**

11 direct rows and 8 indirect rows (19 total).

**Indirect rows:**

| studentName | teacherName |
|---|---|
| Aristotle | Socrates |
| Hannah Arendt | Edmund Husserl |
| Hannah Arendt | Franz Brentano |
| Hans-Georg Gadamer | Edmund Husserl |
| Hans-Georg Gadamer | Franz Brentano |
| Martin Heidegger | Franz Brentano |
| Theophrastus | Plato |
| Theophrastus | Socrates |

**Direct rows:** Aristotle → Plato; Edmund Husserl → Franz Brentano; Gottfried Wilhelm Leibniz → Jakob Thomasius; Hannah Arendt → Martin Heidegger; Hans-Georg Gadamer → Martin Heidegger; Immanuel Kant → Martin Knutzen; Ludwig Wittgenstein → Bertrand Russell; Martin Heidegger → Edmund Husserl; Plato → Socrates; Theophrastus → Aristotle; Thomas Aquinas → Albertus Magnus

## CQ3. Works criticized at least once
**Question:** Which work has been criticized at least once?  
**SPARQL features:** SELECT  
**Ontology evidence path:** `:Engagement -toWork-> :Work`, with `:stance "criticizes"` (defined class `:CriticizedWork`)

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?title
WHERE {
  ?e a :Engagement ; :toWork ?w ; :stance "criticizes" .
  ?w :title ?title .
}
ORDER BY ?title
# Reasoned variant: SELECT ?w WHERE { ?w a :CriticizedWork }
```

**Expected result**

| title |
|---|
| An Enquiry Concerning Human Understanding |
| Being and Time |
| Critique of Pure Reason |
| Republic |
| Tractatus Logico-Philosophicus |


## CQ4. Sub-schools of a school
**Question:** Which schools are sub-schools of a given school?  
**SPARQL features:** SELECT, property path  
**Ontology evidence path:** `:SchoolOfThought -subSchoolOf+-> :SchoolOfThought` (reasoner: `:isWithinSchool`)

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT ?school ?label
WHERE {
  VALUES ?root { :MedievalPhilosophy }
  ?school :subSchoolOf+ ?root ;
          rdfs:label ?label .
}
ORDER BY ?label
# Reasoned variant: ?school :isWithinSchool ?root
```

**Expected result**

**:MedievalPhilosophy** → Scholasticism, Thomism.  
**:AncientGreekPhilosophy** → Peripatetic school, Platonism, Stoicism.  
**:WesternPhilosophy** → 15 schools (every other school in the dataset).

## CQ5. Works that cite or reference a given work
**Question:** Which work cites or references a given work?  
**SPARQL features:** SELECT, UNION  
**Ontology evidence path:** `:Work -references|cites|criticizes|praises-> :Work`, or `:Engagement -fromWork / toWork->`

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?title ?how
WHERE {
  VALUES ?target { :CritiquePureReason }
  { ?w (:references|:cites|:criticizes|:praises) ?target .
    BIND("direct link" AS ?how) }
  UNION
  { ?e a :Engagement ; :fromWork ?w ; :toWork ?target ; :stance ?stance .
    BIND(CONCAT("engagement: ", ?stance) AS ?how) }
  ?w :title ?title .
}
ORDER BY ?title ?how
# Reasoned variant: ?w :references ?target (cites, criticizes, praises are sub-properties)
```

*Note:* The World as Will appears twice because it has two engagements with the Critique (praise for transcendental idealism, criticism of the categories).

**Expected result**

| title | how |
|---|---|
| Prolegomena to Any Future Metaphysics | direct link (:cites) |
| The World as Will and Representation | engagement: criticizes |
| The World as Will and Representation | engagement: praises |


## CQ6. Period of a philosopher
**Question:** Which period does the philosopher belong to?  
**SPARQL features:** SELECT, FILTER  
**Ontology evidence path:** `:Philosopher <-createdBy- :Work -composedDuring-> :TimePeriod`

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?name ?periodLabel
WHERE {
  ?w :createdBy ?p ; :composedDuring ?per .
  ?p rdfs:label ?name .
  ?per rdfs:label ?periodLabel .
  # FILTER (?p = :Kant)
}
ORDER BY ?name
```

**Expected result**

Derived from the periods of the philosopher's works (the ontology has no direct Philosopher → TimePeriod link). Examples: Immanuel Kant → Early modern period; Ludwig Wittgenstein → Twentieth century; Thomas Aquinas → Medieval period. 22 philosophers have at least one work, so the full query returns 22 rows.

## CQ7. Books of interest to a reader
**Question:** Which books might be of interest to a user?  
**SPARQL features:** SELECT, FILTER  
**Ontology evidence path:** `:Reader -hasInterestIn-> :Concept <-aboutConcept- :Engagement -fromWork / toWork-> :Work`

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?title ?conceptLabel
WHERE {
  VALUES ?reader { :reader1 }
  ?reader :hasInterestIn ?c .
  ?e a :Engagement ; :aboutConcept ?c ; (:fromWork|:toWork) ?w .
  ?w :title ?title .
  ?c rdfs:label ?conceptLabel .
}
ORDER BY ?title
```

**Expected result**

**reader1 (Alice)** - interests: Causality, Transcendental idealism.

| title | conceptLabel |
|---|---|
| An Enquiry Concerning Human Understanding | Causality |
| Critique of Pure Reason | Causality |
| Critique of Pure Reason | Transcendental idealism |
| Prolegomena to Any Future Metaphysics | Causality |
| The World as Will and Representation | Transcendental idealism |


## CQ8. Masters who have students
**Question:** Which philosophers are masters and have students?  
**SPARQL features:** SELECT, FILTER EXISTS  
**Ontology evidence path:** `:Philosopher <-studiedUnder- :Philosopher` (defined class `:TeacherThinker`)

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT ?name (COUNT(DISTINCT ?student) AS ?students)
WHERE {
  ?p a :Philosopher ; rdfs:label ?name .
  FILTER EXISTS { ?x :studiedUnder ?p }
  ?student :studiedUnder ?p .
}
GROUP BY ?name
ORDER BY DESC(?students) ?name
# Reasoned variant: SELECT ?p WHERE { ?p a :TeacherThinker }
```

*Definition adopted.* The brief does not define "master", so this project fixes the following operational definition and uses it consistently:

> **master** = a philosopher who is the direct `:studiedUnder` target of at least one other philosopher.

Only *direct* teaching is counted. Transitive ancestry (`:hasTeachingAncestor`) is excluded deliberately: under the transitive reading Socrates would count as the master of Theophrastus, whom he never taught, which is not what the word means in the domain. The OWL defined class `:TeacherThinker` encodes exactly this definition, so the reasoned variant and the SPARQL form agree (both return 10).

**Expected result**

| name | students |
|---|---|
| Martin Heidegger | 2 |
| Albertus Magnus | 1 |
| Aristotle | 1 |
| Bertrand Russell | 1 |
| Edmund Husserl | 1 |
| Franz Brentano | 1 |
| Jakob Thomasius | 1 |
| Martin Knutzen | 1 |
| Plato | 1 |
| Socrates | 1 |


## CQ9. Impact of philosophers
**Question:** What impact did the philosophers have in their era?  
**SPARQL features:** SELECT, aggregation  
**Ontology evidence path:** `:Philosopher <-influencedBy|studiedUnder- :Philosopher`, and `:Engagement -toWork-> :Work -createdBy-> :Philosopher`

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT ?name
       (COUNT(DISTINCT ?follower) AS ?influenced)
       (COUNT(DISTINCT ?e)        AS ?engagementsWithTheirWorks)
WHERE {
  ?p a :Philosopher ; rdfs:label ?name .
  OPTIONAL { ?follower (:influencedBy|:studiedUnder) ?p }
  OPTIONAL { ?w :createdBy ?p . ?e a :Engagement ; :toWork ?w }
}
GROUP BY ?name
HAVING (COUNT(DISTINCT ?follower) + COUNT(DISTINCT ?e) > 0)
ORDER BY DESC(?influenced + ?engagementsWithTheirWorks) ?name
```

*Definition adopted.* "Impact" is not defined in the brief. This project fixes the following operational definition:

> **impact(p)** = |{ q : q `:influencedBy`|`:studiedUnder` p }| + |{ e : e `:toWork` w ∧ w `:createdBy` p }|

That is, the number of distinct later thinkers who name *p* as an influence or teacher, plus the number of recorded engagements that target *p*'s works. The two components are reported separately as well as summed, because they measure different things: the first is influence on *people*, the second is attention paid to *texts*.

Three limitations must be stated with any use of this measure:

1. **It is a measure of what the graph records, not of historical importance.** A philosopher with few digitised engagements scores low regardless of their actual standing.
2. **It is biased by dataset coverage.** Ancient and twentieth-century figures are better represented here than medieval ones, so the ranking partly reflects curation effort.
3. **It ignores the `era` qualifier in the question wording.** The ontology has no direct `Philosopher → TimePeriod` link (see CQ6), so "in their era" cannot be evaluated without first deriving a period from the philosopher's works.

**Expected result**

| name | influenced | engagementsWithTheirWorks |
|---|---|---|
| Aristotle | 3 | 1 |
| Immanuel Kant | 2 | 2 |
| Martin Heidegger | 3 | 1 |
| Plato | 2 | 2 |
| David Hume | 1 | 2 |
| Edmund Husserl | 2 | 1 |
| Arthur Schopenhauer | 2 | 0 |
| John Locke | 2 | 0 |
| René Descartes | 2 | 0 |
| Albertus Magnus | 1 | 0 |
| Bertrand Russell | 1 | 0 |
| Franz Brentano | 1 | 0 |
| Georg Wilhelm Friedrich Hegel | 1 | 0 |
| George Berkeley | 1 | 0 |
| Jakob Thomasius | 1 | 0 |
| Ludwig Wittgenstein | 0 | 1 |
| Martin Knutzen | 1 | 0 |
| Socrates | 1 | 0 |
| Søren Kierkegaard | 1 | 0 |


## CQ10. Cities of philosophers
**Question:** Which cities do philosophers belong to?  
**SPARQL features:** SELECT  
**Ontology evidence path:** `:Philosopher <-createdBy- :Work -createdIn-> :City` (a philosopher "belongs" to the city where their works were created; there is no direct link)

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?name ?cityLabel
WHERE {
  ?w :createdBy ?p ; :createdIn ?city .
  ?city a :City ; rdfs:label ?cityLabel .
  ?p rdfs:label ?name .
}
ORDER BY ?name
```

**Expected result**

| name | cityLabel |
|---|---|
| Aristotle | Athens |
| Immanuel Kant | Königsberg |
| Jean-Paul Sartre | Paris |
| Plato | Athens |
| Theophrastus | Athens |


## CQ11. Concepts a philosopher engages with
**Question:** Which concepts do a given philosopher's works engage with, and how many engagements does each have?  
**SPARQL features:** SELECT, aggregation  
**Ontology evidence path:** `:Philosopher <-createdBy- :Work <-fromWork|toWork- :Engagement -aboutConcept-> :Concept`

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT ?conceptLabel (COUNT(DISTINCT ?e) AS ?engagements)
WHERE {
  VALUES ?p { :Schopenhauer }
  ?w :createdBy ?p .
  ?e a :Engagement ; (:fromWork|:toWork) ?w ; :aboutConcept ?c .
  ?c rdfs:label ?conceptLabel .
}
GROUP BY ?conceptLabel
ORDER BY DESC(?engagements) ?conceptLabel
```

**Expected result**

| conceptLabel | engagements |
|---|---|
| Kantian categories | 1 |
| Transcendental idealism | 1 |


## CQ12. Unread works matching interests
**Question:** Which works has a reader not yet read that match their interests?  
**SPARQL features:** SELECT, FILTER NOT EXISTS  
**Ontology evidence path:** `:Reader -hasInterestIn-> :Concept <-aboutConcept- :Engagement -> :Work`, minus `:Reader -hasRead-> :Work`

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?title ?conceptLabel
WHERE {
  VALUES ?reader { :reader1 }
  ?reader :hasInterestIn ?c .
  ?e a :Engagement ; :aboutConcept ?c ; (:fromWork|:toWork) ?w .
  ?w :title ?title .
  ?c rdfs:label ?conceptLabel .
  FILTER NOT EXISTS { ?reader :hasRead ?w }
}
ORDER BY ?title
```

*Note:* Negation needs FILTER NOT EXISTS because OWL is open-world and cannot express "not yet read".

**Expected result**

**reader1 (Alice)** - has read the Enquiry and the Critique.

| title | conceptLabel |
|---|---|
| Prolegomena to Any Future Metaphysics | Causality |
| The World as Will and Representation | Transcendental idealism |

**reader2 (Bram)** (swap the VALUES) - has read the Republic.

| title | conceptLabel |
|---|---|
| Metaphysics | Theory of Forms |
| Philosophical Investigations | Picture theory of meaning |
| Tractatus Logico-Philosophicus | Picture theory of meaning |


## CQ13. Recommendation with explanation
**Question:** Which unread works are recommended to a reader, and why?  
**SPARQL features:** CONSTRUCT  
**Ontology evidence path:** Same path as CQ12; the CONSTRUCT keeps the supporting triples as the explanation

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
CONSTRUCT {
  ?reader :hasInterestIn ?c .
  ?e a :Engagement ; :fromWork ?from ; :toWork ?to ;
     :aboutConcept ?c ; :stance ?stance ; :confidenceScore ?conf .
  ?w :title ?title ; :createdBy ?author .
  ?author rdfs:label ?authorName .
}
WHERE {
  VALUES ?reader { :reader1 }
  ?reader :hasInterestIn ?c .
  ?e a :Engagement ; :aboutConcept ?c ; :fromWork ?from ; :toWork ?to ;
     :stance ?stance ; :confidenceScore ?conf .
  { BIND(?from AS ?w) } UNION { BIND(?to AS ?w) }
  ?w :title ?title ; :createdBy ?author .
  ?author rdfs:label ?authorName .
  FILTER NOT EXISTS { ?reader :hasRead ?w }
}
```

**Expected result**

For `:reader1` the returned subgraph supports exactly two recommendations:

| recommended work | because (engagement) | concept | stance | confidence |
|---|---|---|---|---|
| Prolegomena to Any Future Metaphysics | eng04 | Causality | praises | 0.7 |
| The World as Will and Representation | eng05 | Transcendental idealism | praises | 0.8 |

The subgraph also contains the other work in each engagement (the Enquiry and the Critique) because the engagement triples are returned whole; the Python layer drops works the reader has already read and ranks the rest by `confidenceScore`.

## CQ14. Does a work have a recorded criticism?
**Question:** Does a given work have a recorded criticism?  
**SPARQL features:** ASK  
**Ontology evidence path:** `:Engagement -toWork-> :Work`, `:stance "criticizes"` (defined class `:CriticizedWork`)

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
ASK {
  ?e a :Engagement ; :toWork :Republic ; :stance "criticizes" .
}
```

**Expected result**

`:Republic` → **true** (eng01, eng02).  `:Meno` → **false** (change `:Republic` to `:Meno`).

## CQ15. Everything known about a work
**Question:** What is everything known about a given work?  
**SPARQL features:** DESCRIBE  
**Ontology evidence path:** All properties of one `:Work` individual

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
DESCRIBE :CritiquePureReason
```

**Expected result**

8 outgoing triples (verified): `rdf:type :Treatise`, `rdf:type owl:NamedIndividual`, `:title` "Critique of Pure Reason", `:createdBy :Kant`, `:composedDuring :EarlyModernPeriod`, `:creationYear "1781"^^xsd:int`, `:createdIn :Konigsberg`, `:belongsToSchool :GermanIdealism`.

The `owl:NamedIndividual` triple is present because every individual in the dataset is now explicitly declared and asserted distinct (`owl:AllDifferent`); see the dataset header for why. Some engines also return incoming triples (the engagements that target this work), and loading `philosophy_links.ttl` adds its `owl:sameAs` and `rdfs:seeAlso` triples as well.

# Rules and checks

## R1. Derive `criticizes` and `praises` shortcut links from engagements

The brief states these links are derived from an Engagement's stance by a SPARQL CONSTRUCT or SWRL rule, because OWL cannot do it. Run both and insert the results into the graph.

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
CONSTRUCT { ?a :criticizes ?b }
WHERE     { ?e a :Engagement ; :fromWork ?a ; :toWork ?b ; :stance "criticizes" }

CONSTRUCT { ?a :praises ?b }
WHERE     { ?e a :Engagement ; :fromWork ?a ; :toWork ?b ; :stance "praises" }
```

**Expected:** 6 `criticizes` links and 3 `praises` links (`neutral` engagements produce none).

| link | from work | to work |
|---|---|---|
| criticizes | Being and Nothingness | Being and Time |
| criticizes | Critique of Pure Reason | An Enquiry Concerning Human Understanding |
| criticizes | Metaphysics | Republic |
| criticizes | Nicomachean Ethics | Republic |
| criticizes | Philosophical Investigations | Tractatus Logico-Philosophicus |
| criticizes | The World as Will and Representation | Critique of Pure Reason |
| praises | Being and Time | Logical Investigations |
| praises | Prolegomena to Any Future Metaphysics | An Enquiry Concerning Human Understanding |
| praises | The World as Will and Representation | Critique of Pure Reason |

The World as Will and Representation → Critique of Pure Reason receives **both** links (two engagements about different concepts). This is why the ontology deliberately does not declare `criticizes` and `praises` disjoint.

## R2. Quick consistency probes

```sparql
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
# Philosophers with no school recorded (data gap, not an error)
SELECT ?name WHERE {
  ?p a :Philosopher ; rdfs:label ?name .
  FILTER NOT EXISTS { ?p :belongsToSchool ?s }
} ORDER BY ?name
```

**Expected:** 10 rows - Arthur Schopenhauer, Franz Brentano, Friedrich Nietzsche, Hannah Arendt, Hans-Georg Gadamer, Jakob Thomasius, John Stuart Mill, Karl Marx, Martin Knutzen, Socrates.

# Evidence-path summary (for the evaluation of the LLM system)

Every expected answer above is traceable to concrete triples. For the 15-question evaluation, the "gold" answer for each CQ is the Expected table, and the ontology evidence path is the line under each query. Run the questions against both systems with the same wording and record whether the answer can be linked back to one of these paths.
