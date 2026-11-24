# OWL 2 constructs used in this ontology

Companion to `philosophy_ontology.ttl`. Every construct is given in **Turtle** and in
**RDF/XML**, with a line-by-line breakdown, following the format of Week 9, Lecture 9.
The RDF/XML in this document was generated from the Turtle source with RDFLib, so the
two serialisations are guaranteed to be the same axioms.

All axioms below are verified: HermiT reports the ontology **consistent with 0
unsatisfiable classes**, and the member counts quoted are what HermiT actually infers
(`python3 build.py`, step 4).

---

## Coverage summary

| Construct | Count | Where |
|---|---|---|
| `owl:someValuesFrom` | 4 | `StudentThinker`, `TeacherThinker`, `InfluencerThinker`, `CriticizedWork` |
| `owl:allValuesFrom` | 1 | `UncriticizedWork` |
| `owl:complementOf` | 1 | `UncriticizedWork` |
| `owl:hasValue` | 3 | `CriticizedWork`, `Criticism`, `UncriticizedWork` |
| `owl:hasSelf` | 1 | `SelfReferentialWork` |
| `owl:oneOf` | 1 | `stance` datatype range |
| `owl:intersectionOf` | 7 | all defined classes |
| `owl:unionOf` | 1 | `belongsToSchool` domain |
| `owl:minQualifiedCardinality` | 1 | `ProlificPhilosopher` |
| `owl:qualifiedCardinality` | 3 | `Engagement` |
| `owl:propertyChainAxiom` | 2 | `createdInLineageOf`, `createdIn` |
| `owl:hasKey` | 1 | `Philosopher` |
| `owl:AllDisjointClasses` | 1 | the seven top-level categories |
| `owl:propertyDisjointWith` | 1 | `studiedUnder` / `hasRead` |
| `owl:AllDifferent` | 1 | all 109 individuals |
| `owl:NamedIndividual` | 109 | every individual |
| `owl:FunctionalProperty` | 10 | — |
| `owl:TransitiveProperty` | 3 | `locatedIn`, `hasTeachingAncestor`, `isWithinSchool` |
| `owl:AsymmetricProperty` | 2 | `subSchoolOf`, `studiedUnder` |
| `owl:IrreflexiveProperty` | 3 | `subSchoolOf`, `studiedUnder`, `influencedBy` |
| `owl:inverseOf` | 4 | `createdBy`/`authored` and three inline inverses |
| `owl:disjointWith` | 7 | `Reader`, `Country`/`City` |
| `owl:withRestrictions` | 1 | `confidenceScore` ∈ [0,1] |

---

## 1. `owl:allValuesFrom` + `owl:complementOf` — `UncriticizedWork`

**Mirrors lecture Example #1** (`AvailableBook` = a `Book` lent to no `Member`).

A work is uncriticized if and only if it is a `Work` **and** every engagement pointing
at it is *not* an engagement whose stance is `"criticizes"`.

> UncriticizedWork ≡ Work ⊓ ∀toWork⁻.(¬(∃stance.{"criticizes"}))

### Turtle

```turtle
:UncriticizedWork a owl:Class ;
    owl:equivalentClass [ a owl:Class ;
        owl:intersectionOf ( :Work
            [ a owl:Restriction ;
              owl:onProperty [ owl:inverseOf :toWork ] ;
              owl:allValuesFrom [ a owl:Class ;
                  owl:complementOf [ a owl:Restriction ;
                      owl:onProperty :stance ;
                      owl:hasValue "criticizes" ] ] ] ) ] .
```

### RDF/XML

```xml
<owl:Class rdf:about="#UncriticizedWork">
  <owl:equivalentClass>
    <owl:Class>
      <owl:intersectionOf rdf:parseType="Collection">
        <rdf:Description rdf:about="#Work"/>
        <owl:Restriction>
          <owl:onProperty>
            <rdf:Description>
              <owl:inverseOf rdf:resource="#toWork"/>
            </rdf:Description>
          </owl:onProperty>
          <owl:allValuesFrom>
            <owl:Class>
              <owl:complementOf>
                <owl:Restriction>
                  <owl:onProperty rdf:resource="#stance"/>
                  <owl:hasValue>criticizes</owl:hasValue>
                </owl:Restriction>
              </owl:complementOf>
            </owl:Class>
          </owl:allValuesFrom>
        </owl:Restriction>
      </owl:intersectionOf>
    </owl:Class>
  </owl:equivalentClass>
</owl:Class>
```

### Line by line

| Element | Logical meaning | What it does |
|---|---|---|
| `<owl:Class rdf:about="#UncriticizedWork">` | `UncriticizedWork` is a class | Declares the named class. |
| `<owl:equivalentClass>` | `≡`, not `⊑` | "A work is uncriticized **if and only if** …". `subClassOf` would only give the one-way implication, and the reasoner could then never *infer* membership. |
| `<owl:Class>` (unnamed) | an anonymous class expression | The right-hand side of the equivalence; it has no name, only a structure. |
| `<owl:intersectionOf rdf:parseType="Collection">` | `C₁ ⊓ C₂` | `parseType="Collection"` makes the parser build an RDF list (`rdf:first`/`rdf:rest`/`rdf:nil`) from the children. |
| `<rdf:Description rdf:about="#Work"/>` | `C₁ = Work` | First conjunct. |
| `<owl:Restriction>` | `C₂ = (…)` | Second conjunct: an anonymous class defined by a condition on a property. |
| `<owl:inverseOf rdf:resource="#toWork"/>` | `toWork⁻` | An **inline inverse property expression**. We need "engagements pointing *at* this work", but `toWork` runs Engagement → Work, so the inverse is taken without naming a new property. |
| `<owl:allValuesFrom>` | `∀toWork⁻.(…)` | Universal restriction: *every* incoming engagement must satisfy the filler. |
| `<owl:complementOf>` | `¬(…)` | Negation: the filler is everything that is **not** the class inside. |
| `<owl:hasValue>criticizes</owl:hasValue>` | `∃stance.{"criticizes"}` | A value restriction on a *data* property: the stance literal is exactly `"criticizes"`. |

### Result and why it is 0

HermiT infers **0 members**, and that is the pedagogically interesting part.

A `∀` restriction is satisfied vacuously by anything with no incoming `toWork` edge, so
you might expect the 17 works that appear in no engagement at all to classify here. They
do not, because of the **open-world assumption**: OWL does not know the engagement list
is complete.
For all the reasoner knows, a criticizing engagement exists that simply has not been
written down. It therefore refuses to conclude anything.

This is the same limitation that forces CQ12 ("works a reader has *not* read") into
SPARQL `FILTER NOT EXISTS` rather than OWL. To make the class non-empty you would have to
close the world explicitly for each work, e.g.

```turtle
:Meno a [ a owl:Restriction ;
          owl:onProperty [ owl:inverseOf :toWork ] ;
          owl:maxCardinality "0"^^xsd:nonNegativeInteger ] .
```

The class is kept empty on purpose: it documents the OWA boundary rather than hiding it.

---

## 2. `owl:minQualifiedCardinality` — `ProlificPhilosopher`

> ProlificPhilosopher ≡ Philosopher ⊓ ≥3 authored.Work

### Turtle

```turtle
:ProlificPhilosopher a owl:Class ;
    owl:equivalentClass [ a owl:Class ;
        owl:intersectionOf ( :Philosopher
            [ a owl:Restriction ;
              owl:onProperty :authored ;
              owl:minQualifiedCardinality "3"^^xsd:nonNegativeInteger ;
              owl:onClass :Work ] ) ] .
```

### RDF/XML

```xml
<owl:Class rdf:about="#ProlificPhilosopher">
  <owl:equivalentClass>
    <owl:Class>
      <owl:intersectionOf rdf:parseType="Collection">
        <rdf:Description rdf:about="#Philosopher"/>
        <owl:Restriction>
          <owl:onProperty rdf:resource="#authored"/>
          <owl:minQualifiedCardinality
              rdf:datatype="http://www.w3.org/2001/XMLSchema#nonNegativeInteger"
              >3</owl:minQualifiedCardinality>
          <owl:onClass rdf:resource="#Work"/>
        </owl:Restriction>
      </owl:intersectionOf>
    </owl:Class>
  </owl:equivalentClass>
</owl:Class>
```

### Line by line

| Element | Logical meaning | What it does |
|---|---|---|
| `<owl:onProperty rdf:resource="#authored"/>` | the restriction concerns `authored` | `authored` is itself inferred, as the `owl:inverseOf` of `createdBy`; no `authored` triple is asserted anywhere in the dataset. |
| `<owl:minQualifiedCardinality>3</…>` | `≥ 3` | *Qualified* cardinality: at least three values **of a stated class**. The unqualified `owl:minCardinality` would not let us say "three *Works*". |
| `<owl:onClass rdf:resource="#Work"/>` | `.Work` | The qualifying class. `onClass` is only legal together with a `…QualifiedCardinality`. |

### Result: 2 members, and why the number depends on `owl:AllDifferent`

HermiT infers **Plato** and **Kant** (3 works each in the dataset).

Measured on this project, the same axiom returns **1 member without** the
`owl:AllDifferent` axiom in the dataset and **2 with** it. OWL makes **no unique-name
assumption**: absent an explicit statement, `:Republic`, `:Phaedo` and `:Meno` *could* be
three names for one book, in which case Plato would have one work, not three. Declaring
all 109 individuals pairwise distinct is what licenses the count.

This is the single most important reason the dataset declares `owl:AllDifferent`, and it
is why the lecture pairs `owl:oneOf` with `owl:AllDifferent` in Example #2.

---

## 3. `owl:hasValue` — `Criticism`

**Mirrors lecture Example #5** (`FirstClassPassengers` = `travelsIn` value `First`).

> Criticism ≡ Engagement ⊓ ∃stance.{"criticizes"}

### Turtle

```turtle
:Criticism a owl:Class ;
    owl:equivalentClass [ a owl:Class ;
        owl:intersectionOf ( :Engagement
            [ a owl:Restriction ;
              owl:onProperty :stance ;
              owl:hasValue "criticizes" ] ) ] .
```

### RDF/XML

```xml
<owl:Class rdf:about="#Criticism">
  <owl:equivalentClass>
    <owl:Class>
      <owl:intersectionOf rdf:parseType="Collection">
        <rdf:Description rdf:about="#Engagement"/>
        <owl:Restriction>
          <owl:onProperty rdf:resource="#stance"/>
          <owl:hasValue>criticizes</owl:hasValue>
        </owl:Restriction>
      </owl:intersectionOf>
    </owl:Class>
  </owl:equivalentClass>
</owl:Class>
```

The lecture example restricts an **object** property to a named individual
(`travelsIn value :First`); here the same construct restricts a **datatype** property to
a literal. Both are legal `owl:hasValue`.

**Result: 6 members** — `eng01`, `eng02`, `eng03`, `eng06`, `eng07`, `eng09`. This matches
the 6 rows produced by the `CONSTRUCT` rule R1 in the query collection, which is a useful
cross-check: the OWL class and the SPARQL rule agree.

---

## 4. `owl:hasSelf` — `SelfReferentialWork`

**Mirrors lecture Example #6** (`SelfEvaluator` = a `Lecturer` who `evaluates` itself).

> SelfReferentialWork ≡ ∃references.Self

### Turtle

```turtle
:SelfReferentialWork a owl:Class ;
    owl:equivalentClass [ a owl:Restriction ;
        owl:onProperty :references ;
        owl:hasSelf "true"^^xsd:boolean ] .
```

### RDF/XML

```xml
<owl:Class rdf:about="#SelfReferentialWork">
  <owl:equivalentClass>
    <owl:Restriction>
      <owl:onProperty rdf:resource="#references"/>
      <owl:hasSelf rdf:datatype="http://www.w3.org/2001/XMLSchema#boolean"
          >true</owl:hasSelf>
    </owl:Restriction>
  </owl:equivalentClass>
</owl:Class>
```

Note there is **no `owl:intersectionOf`** here: the whole class is a single restriction,
so the `equivalentClass` value is the `owl:Restriction` directly. This matches the
lecture's `SelfEvaluator` exactly.

**Result: 0 members**, as intended. The class is a deliberate OWL-level mirror of the
SHACL constraint "A work must not reference itself" (`:WorkShape`). Two independent
mechanisms check the same rule, which is why the build runs both.

---

## 5. `owl:qualifiedCardinality` — exactly one source, target and concept

Section 9 of the design brief claims each `Engagement` has *exactly* one `fromWork`,
`toWork` and `aboutConcept`. `owl:FunctionalProperty` only delivers **at most one**, so
on its own it under-states the claim.

### Turtle

```turtle
:Engagement rdfs:subClassOf
    [ a owl:Restriction ; owl:onProperty :fromWork ;
      owl:qualifiedCardinality "1"^^xsd:nonNegativeInteger ; owl:onClass :Work ] ,
    [ a owl:Restriction ; owl:onProperty :toWork ;
      owl:qualifiedCardinality "1"^^xsd:nonNegativeInteger ; owl:onClass :Work ] ,
    [ a owl:Restriction ; owl:onProperty :aboutConcept ;
      owl:qualifiedCardinality "1"^^xsd:nonNegativeInteger ; owl:onClass :Concept ] .
```

### RDF/XML

```xml
<owl:Class rdf:about="#Engagement">
  <rdfs:subClassOf>
    <owl:Restriction>
      <owl:onProperty rdf:resource="#fromWork"/>
      <owl:qualifiedCardinality
          rdf:datatype="http://www.w3.org/2001/XMLSchema#nonNegativeInteger"
          >1</owl:qualifiedCardinality>
      <owl:onClass rdf:resource="#Work"/>
    </owl:Restriction>
  </rdfs:subClassOf>
  <!-- the toWork and aboutConcept restrictions follow the same shape -->
</owl:Class>
```

`rdfs:subClassOf` is correct here, not `owl:equivalentClass`: having exactly one source
work does not *make* something an engagement.

**This does not replace the SHACL shapes.** Under the open-world assumption OWL will never
report a *missing* `fromWork` — it simply assumes one exists that has not been recorded.
Only SHACL, which is closed-world, can fail validation for an absent value. The two are
complementary, and `philosophy_shapes.ttl` keeps its `sh:minCount 1` for exactly this
reason.

---

## 6. `owl:hasKey` — entity matching

> Two philosophers with the same `externalId` are the same philosopher.

```turtle
:Philosopher owl:hasKey ( :externalId ) .
```

```xml
<owl:Class rdf:about="#Philosopher">
  <owl:hasKey rdf:parseType="Collection">
    <rdf:Description rdf:about="#externalId"/>
  </owl:hasKey>
</owl:Class>
```

This delivers the entity-matching story promised in Section 2 of the design brief. It is
preferred over `owl:InverseFunctionalProperty` on a datatype property, which OWL 2 DL
forbids outright; `owl:hasKey` is **DL-safe**, applying only to named individuals.

Two preconditions had to be met before the axiom was sound:

1. **The key must be total.** All 31 philosophers now carry an `externalId`; earlier only
   10 did.
2. **The values must be verified.** All 31 QIDs were resolved against the live Wikidata
   API and confirmed by birth year, not by label match.

`:Work` deliberately has **no** key: only works with an en.wikipedia article were given an
`externalId`, so the property is partial there.

> **Tool bug worth knowing about.** `owlrl` 7.6.2 mis-implements `prp-key` for
> single-property keys — its comparison loop runs `range(0, len(keys) - 1)`, which is
> empty when there is one key, so every individual of the class is merged. On this
> ontology that produces 4,352 bogus `owl:sameAs` triples and inflates
> `hasTeachingAncestor` from 19 to 961. HermiT is unaffected. `build.py` strips the axiom
> for its OWL-RL step and asserts that no non-reflexive `owl:sameAs` is ever inferred.

---

## 7. `owl:AllDisjointClasses` — the seven top-level categories

```turtle
[] a owl:AllDisjointClasses ;
   owl:members ( :Philosopher :Work :Engagement :Concept :SchoolOfThought
                 :Location :TimePeriod ) .
```

```xml
<owl:AllDisjointClasses>
  <owl:members rdf:parseType="Collection">
    <rdf:Description rdf:about="#Philosopher"/>
    <rdf:Description rdf:about="#Work"/>
    <rdf:Description rdf:about="#Engagement"/>
    <rdf:Description rdf:about="#Concept"/>
    <rdf:Description rdf:about="#SchoolOfThought"/>
    <rdf:Description rdf:about="#Location"/>
    <rdf:Description rdf:about="#TimePeriod"/>
  </owl:members>
</owl:AllDisjointClasses>
```

The OWL 2 **n-ary** form. It is equivalent to 21 separate `owl:disjointWith` axioms
(7 × 6 / 2) but is one statement instead of 21, and the subject is a blank node because
the axiom is about the *set*, not about any one class.

`:Reader` is the deliberate exception and stays outside this list: it is disjoint from the
other six but **not** from `:Philosopher`, because a philosopher reads other philosophers'
works. `:Russell` is both in the dataset.

---

## 8. `owl:AllDifferent` — no unique-name assumption

```turtle
[] a owl:AllDifferent ;
   owl:distinctMembers ( :Socrates :Plato :Aristotle … ) .   # all 109
```

```xml
<owl:AllDifferent>
  <owl:distinctMembers rdf:parseType="Collection">
    <rdf:Description rdf:about="#Socrates"/>
    <rdf:Description rdf:about="#Plato"/>
    <!-- … 107 more … -->
  </owl:distinctMembers>
</owl:AllDifferent>
```

Directly follows the lecture's Example #2, where the four string instruments are declared
`owl:NamedIndividual` and then `owl:AllDifferent` so that the enumerated class has exactly
four members. The measured effect on this project is documented under
`ProlificPhilosopher` above: 1 member without it, 2 with it.

---

## 9. `owl:propertyChainAxiom` — inference across two hops

```turtle
:createdInLineageOf owl:propertyChainAxiom ( :createdBy :hasTeachingAncestor ) .
:createdIn          owl:propertyChainAxiom ( :createdIn :locatedIn ) .
```

```xml
<owl:ObjectProperty rdf:about="#createdInLineageOf">
  <owl:propertyChainAxiom rdf:parseType="Collection">
    <rdf:Description rdf:about="#createdBy"/>
    <rdf:Description rdf:about="#hasTeachingAncestor"/>
  </owl:propertyChainAxiom>
</owl:ObjectProperty>
```

Read the first as: if work *w* was `createdBy` *p*, and *p* `hasTeachingAncestor` *q*, then
*w* `createdInLineageOf` *q*. It answers "show me works written by anyone in Plato's
teaching line" without storing a single `createdInLineageOf` triple — **27** are inferred
from **0** asserted.

The second is a chain on the property itself, which propagates a work's location up the
place hierarchy: a work created in Athens is thereby also created in Greece. It takes
`createdIn` from 10 asserted to **20** inferred triples.

---

## 10. `owl:oneOf` and `owl:withRestrictions` — constrained datatypes

```turtle
:stance rdfs:range [ a rdfs:Datatype ;
                     owl:oneOf ( "praises" "criticizes" "neutral" ) ] .

:confidenceScore rdfs:range [ a rdfs:Datatype ;
                     owl:onDatatype xsd:decimal ;
                     owl:withRestrictions ( [ xsd:minInclusive 0.0 ]
                                            [ xsd:maxInclusive 1.0 ] ) ] .
```

`owl:oneOf` over literals is the datatype analogue of the lecture's enumerated
`StringInstruments` class. Any fourth stance value makes the ontology **inconsistent**,
which the reasoner reports immediately — a stronger guarantee than a SHACL warning.

`owl:withRestrictions` builds a *derived datatype*: `xsd:decimal` narrowed to the closed
interval [0, 1]. This is the OWL 2 facet mechanism, equivalent to an XML Schema
`restriction` with `minInclusive`/`maxInclusive`.

---

## 11. Property characteristics, and one modelling subtlety

```turtle
:subSchoolOf   a owl:ObjectProperty , owl:AsymmetricProperty , owl:IrreflexiveProperty ;
               rdfs:subPropertyOf :isWithinSchool .
:isWithinSchool a owl:ObjectProperty , owl:TransitiveProperty .

:studiedUnder  a owl:ObjectProperty , owl:AsymmetricProperty , owl:IrreflexiveProperty ;
               rdfs:subPropertyOf :hasTeachingAncestor , :influencedBy .
:hasTeachingAncestor a owl:ObjectProperty , owl:TransitiveProperty .
```

This pairing is forced by OWL 2 DL, and it is worth stating explicitly because it looks
redundant at first glance.

A property that is **transitive** is a *non-simple* property, and OWL 2 DL **forbids**
declaring a non-simple property asymmetric or irreflexive — allowing it would make
reasoning undecidable. So `studiedUnder` cannot be both "asymmetric" and "transitive".

The resolution is to split the relation in two:

- `studiedUnder` — the **direct**, asserted teacher–pupil link. Simple, so it may be
  asymmetric and irreflexive.
- `hasTeachingAncestor` — its **transitive super-property**, used only for inference.

Asserting `studiedUnder` therefore also yields `hasTeachingAncestor`, whose transitive
closure gives the full lineage: 11 asserted links produce **19** inferred ancestor pairs.
The same pattern applies to `subSchoolOf` / `isWithinSchool` (15 asserted → 26 inferred).

`influencedBy` is deliberately **not** transitive: influence weakens along a chain, and
making it transitive would claim Socrates directly influenced every later philosopher.
