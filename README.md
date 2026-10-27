# FOLIO Insights

Turn legal sources into flat, FOLIO-tagged propositions.

FOLIO Insights reads judicial opinions, briefs, statutes, treatises, journal articles, and practitioner know-how. It pulls out **insights (propositions)**: short, atomic statements a source makes, such as "A plaintiff must prove damages to recover more than nominal damages." Each insight keeps the verbatim source span it rests on, and the pipeline tags it with as many of the [FOLIO legal ontology](https://github.com/alea-institute/FOLIO)'s 18,000+ concepts as apply: who owes what duty, what the law permits or prohibits, the exceptions, the penalties, the area of law, the forum, and the actors. You get one SHACL-validated OWL module, plus Turtle, JSON-LD, HTML, and Markdown.

The pipeline extracts; it does not generate. It records what a source says, never judges legal merit, and never rewrites the text. Ideas, not expressions.

```mermaid
flowchart LR
    A[Source document] --> B[Extract insight / proposition]
    B --> C[Ground in a verbatim span]
    C --> D[Tag with FOLIO concepts, many per insight]
    D --> E[Validate with SHACL]
    E --> F[Export OWL, Turtle, JSON-LD, HTML, Markdown]
```

## Contents

- [One proposition, many tags](#one-proposition-many-tags)
- [Examples by source type](#examples-by-source-type)
- [Who it's for](#who-its-for)
- [What you get](#what-you-get)
- [Try it](#try-it)
- [Review viewer](#review-viewer)
- [How it works](#how-it-works)
- [Status](#status)
- [More commands](#more-commands)
- [Contributing](#contributing)

## One proposition, many tags

An insight carries no hierarchy. It holds one proposition, its source span, and a flat list of FOLIO tags drawn from whichever branches of the ontology apply. Take subdivision (a) of the synthetic statute in Example 5:

> A business that discovers a data breach must notify each affected resident within 45 days after discovery.

| FOLIO branch | FOLIO concept |
|---|---|
| Deontic Specification | [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) |
| Event | [Data Breach](https://folio.openlegalstandard.org/Raw03V8d0o2ILRa4VEpq4t) |
| Document / Artifact | [Notice](https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7) |
| Area of Law | [Privacy Law](https://folio.openlegalstandard.org/R8hJCf4Ih6iuFXsxeK7e6zU), [Consumer Protection Law](https://folio.openlegalstandard.org/RCovPJMo8mH3uZhlySLgWIa) |
| Legal Authorities | [Statutes](https://folio.openlegalstandard.org/RHagFJXtPsCCn5dbENWLNR) |

FOLIO's [Deontic Specification](https://folio.openlegalstandard.org/RClhbl4E1TJp9LygIXewIhn) branch, part of its Objectives branch, names the normative force of a proposition: [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) for a duty ("shall", "must"), [Permission](https://folio.openlegalstandard.org/RCurUksxnjgPwYWpCSq0xPI) for "may", [Prohibition](https://folio.openlegalstandard.org/RCqqI0SLTxsE8Z2rCu7KOXm) for "must not", [Exception](https://folio.openlegalstandard.org/RCdJXw1Ml7DIBqmouWarZm2) for "unless" and "except", plus [Right](https://folio.openlegalstandard.org/RmCCZU8GS7O8920pkDipw7), [Waiver](https://folio.openlegalstandard.org/R9CBXdybYDztLBRNDNJl0W), [Violation](https://folio.openlegalstandard.org/RDsDXHKUsZoJfz87jnz7zjj), [Compliance](https://folio.openlegalstandard.org/RCZwssbqfmu0Lds0LPDV34F), and [Authority](https://folio.openlegalstandard.org/R9ikrznaQwm4RUsMzP9KXFR). Penalties come from [Regulatory Penalty](https://folio.openlegalstandard.org/R6DLuG3VglXIci9EJ3MwAK) (Objectives › Regulatory Objectives) for statutory fines and [Penalty Clause](https://folio.openlegalstandard.org/RCNKm9EnW4P2a7noaWhJg4j) (Objectives › Transactional Objectives) for contract terms. The other tags come from branches such as Area of Law, Actor / Player, Event, Document / Artifact, Forums and Venues, Legal Authorities, Legal Entity, Location, and Service.

`folio-insights extract` writes the insight as a knowledge unit. Field names come from the `KnowledgeUnit`, `Span`, and `ConceptTag` models; `branch` records each tag's top-level FOLIO branch. The values illustrate; lineage and the coarse `unit_type` are trimmed:

```json
{
  "text": "A business that discovers a data breach must notify each affected resident within 45 days after discovery.",
  "source_file": "nland-stat-325X04.txt",
  "original_span": {"source_file": "nland-stat-325X04.txt", "start": 4, "end": 110},
  "source_snippet": "…",
  "anchor_verified": true,
  "anchor_score": 1.0,
  "confidence": 0.93,
  "folio_tags": [
    {"label": "Obligation", "iri": "https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao", "branch": "Objectives", "confidence": 0.95, "extraction_path": "llm"},
    {"label": "Data Breach", "iri": "https://folio.openlegalstandard.org/Raw03V8d0o2ILRa4VEpq4t", "branch": "Event", "confidence": 0.97, "extraction_path": "entity_ruler"},
    {"label": "Notice", "iri": "https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7", "branch": "Document / Artifact", "confidence": 0.92, "extraction_path": "entity_ruler"},
    {"label": "Privacy Law", "iri": "https://folio.openlegalstandard.org/R8hJCf4Ih6iuFXsxeK7e6zU", "branch": "Area of Law", "confidence": 0.89, "extraction_path": "llm"},
    {"label": "Consumer Protection Law", "iri": "https://folio.openlegalstandard.org/RCovPJMo8mH3uZhlySLgWIa", "branch": "Area of Law", "confidence": 0.81, "extraction_path": "llm"},
    {"label": "Statutes", "iri": "https://folio.openlegalstandard.org/RHagFJXtPsCCn5dbENWLNR", "branch": "Legal Authorities", "confidence": 0.86, "extraction_path": "heading_context"}
  ]
}
```

The unit may paraphrase, but `source_snippet` holds the exact source substring at `original_span` (elided here; the repository's exclusion scanner keeps excerpt values out of tracked files), and `anchor_verified` records whether the match cleared the 0.85 threshold. A deterministic resolver turns tag labels into FOLIO IRIs; no model ever writes an IRI.

## Examples by source type

> **Synthetic examples. Excerpts are invented for illustration.** Every case, party, docket, firm, journal, and statute below is fictional. The FOLIO tags are real: each links to its live class, and each branch label names a real FOLIO ancestor of that class, checked against the 18,323-class FOLIO release.

Each table lists the insights (propositions) a run should pull from the excerpt above it. **Source span** quotes the excerpt verbatim; that quote anchors the insight. **FOLIO tags** groups each insight's tags by branch. Deontic Specification, Litigation Objectives, Transactional Objectives, and Regulatory Objectives all sit inside FOLIO's Objectives branch.

<details open>
<summary><strong>1. Judicial opinion</strong>: contract elements, damages, and an exception to a no-oral-modification clause</summary>

> *Harlow v. Brightwater Logistics, Inc.*, No. 27-CV-24-0117 (Minn. Dist. Ct. 2025) (synthetic)
>
> To prevail on a breach-of-contract claim, a plaintiff must prove (1) the formation of a contract, (2) the plaintiff's performance of any conditions precedent, and (3) the defendant's breach. A plaintiff must prove damages to recover more than nominal damages, but nominal damages remain available for any proven breach. Summary judgment is appropriate only when no genuine dispute of material fact exists and the movant is entitled to judgment as a matter of law. A written contract that bars oral modification ordinarily controls, except where the party seeking enforcement has waived the bar by its own conduct. Here, Brightwater accepted late deliveries for eight months without objection, so a jury could find waiver. The motion is DENIED.

| Insight (proposition) | Source span | FOLIO tags |
|---|---|---|
| A plaintiff claiming breach of contract must prove formation, its own performance of conditions precedent, and the defendant's breach. | "a plaintiff must prove (1) the formation of a contract" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Litigation Objectives:** [Breach of Contract](https://folio.openlegalstandard.org/RC2fjcpsEbrVvVymvt4oASx), [Litigation Burdens of Proof](https://folio.openlegalstandard.org/RDV74m3ydS2I72hZ88Mf1RX) · **Area of Law:** [Contract Law](https://folio.openlegalstandard.org/RCIPwpgRpMs1eVz4vPid0pV) · **Actor / Player:** [Plaintiff](https://folio.openlegalstandard.org/R9tyJmIM3Lx7OItGji5zPXN), [Defendant](https://folio.openlegalstandard.org/RijIqw1HEfQF4ctjWUlgnq) |
| A plaintiff must prove damages to recover more than nominal damages. | "A plaintiff must prove damages to recover more than nominal damages" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Litigation Objectives:** [Damages](https://folio.openlegalstandard.org/RCCv5YLoHUOm5AlqcCBzqGf), [Nominal Damages](https://folio.openlegalstandard.org/RwdhuuPLbMNn3T9mxGZGPH) · **Area of Law:** [Contract Law](https://folio.openlegalstandard.org/RCIPwpgRpMs1eVz4vPid0pV) · **Actor / Player:** [Plaintiff](https://folio.openlegalstandard.org/R9tyJmIM3Lx7OItGji5zPXN) |
| Summary judgment requires no genuine dispute of material fact and a movant entitled to judgment as a matter of law. | "no genuine dispute of material fact exists" | **Document / Artifact:** [Summary Judgment](https://folio.openlegalstandard.org/R8K6VFq9c39kbQouame6Onf), [Judicial Opinion](https://folio.openlegalstandard.org/RDNaE3PFsXDfIudTq7w3ace) · **Forums and Venues:** [Minnesota District Court](https://folio.openlegalstandard.org/RxLV9XEaDWbDIA8N1fl2fM) · **Location:** [Minnesota](https://folio.openlegalstandard.org/RDB9ffc13Cb117D7caa05f07) |
| A no-oral-modification clause controls unless the party seeking enforcement waived it by its own conduct. | "except where the party seeking enforcement has waived the bar by its own conduct" | **Deontic Specification:** [Exception](https://folio.openlegalstandard.org/RCdJXw1Ml7DIBqmouWarZm2), [Waiver](https://folio.openlegalstandard.org/R9CBXdybYDztLBRNDNJl0W) · **Transactional Objectives:** [Modification of Agreement Clause](https://folio.openlegalstandard.org/RZSIXV7riyj3JVeY7qDJPR) · **Document / Artifact:** [Oral Agreement](https://folio.openlegalstandard.org/R7wrI57WaogjWdkpozaYZyV) · **Area of Law:** [Contract Law](https://folio.openlegalstandard.org/RCIPwpgRpMs1eVz4vPid0pV) |
| Accepting late deliveries for months without objection lets a jury find waiver. | "accepted late deliveries for eight months without objection, so a jury could find waiver" | **Deontic Specification:** [Waiver](https://folio.openlegalstandard.org/R9CBXdybYDztLBRNDNJl0W) · **Litigation Objectives:** [Breach of Contract](https://folio.openlegalstandard.org/RC2fjcpsEbrVvVymvt4oASx) · **Actor / Player:** [Jury](https://folio.openlegalstandard.org/R9pwejG33H0Y9mi74WzE2nb) |

</details>

<details>
<summary><strong>2. Brief</strong>: a motion to dismiss for lack of personal jurisdiction</summary>

> Defendant's Memorandum in Support of Motion to Dismiss, *Osterberg Outdoor Supply Co. v. Quillfeather Ceramics GmbH*, No. 25-cv-2290 (D. Minn.) (synthetic)
>
> Plaintiff bears the burden of making a prima facie showing of personal jurisdiction over each defendant. Quillfeather has no office, employees, or bank accounts in Minnesota, and it shipped no product here; a distributor resold the mugs without Quillfeather's direction. The mere foreseeability that a product may reach the forum state does not establish purposeful availment. *Ostrander v. Pell Manufacturing Co.*, No. 22-cv-0940 (D. Minn. 2023). Quillfeather supports this motion with a sworn declaration, which shifts the burden to Plaintiff to come forward with evidence, not allegations.

| Insight (proposition) | Source span | FOLIO tags |
|---|---|---|
| The plaintiff must make a prima facie showing of personal jurisdiction over each defendant. | "Plaintiff bears the burden of making a prima facie showing of personal jurisdiction" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Litigation Objectives:** [Personal Jurisdiction](https://folio.openlegalstandard.org/RinqHf65TtUhr762WKqN6R), [Litigation Burdens of Proof](https://folio.openlegalstandard.org/RDV74m3ydS2I72hZ88Mf1RX) · **Actor / Player:** [Plaintiff](https://folio.openlegalstandard.org/R9tyJmIM3Lx7OItGji5zPXN), [Defendant](https://folio.openlegalstandard.org/RijIqw1HEfQF4ctjWUlgnq) |
| Foreseeability that a product reaches the forum state does not establish purposeful availment. | "foreseeability that a product may reach the forum state does not establish purposeful availment" | **Litigation Objectives:** [Personal Jurisdiction](https://folio.openlegalstandard.org/RinqHf65TtUhr762WKqN6R) · **Actor / Player:** [Defendant](https://folio.openlegalstandard.org/RijIqw1HEfQF4ctjWUlgnq) · **Location:** [Minnesota](https://folio.openlegalstandard.org/RDB9ffc13Cb117D7caa05f07) · **Document / Artifact:** [Brief / Memorandum of Law](https://folio.openlegalstandard.org/R8wEzsnWA30YRmdfZKRkFuH) |
| A sworn declaration shifts the burden to the plaintiff to come forward with evidence, not allegations. | "supports this motion with a sworn declaration, which shifts the burden to Plaintiff" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Document / Artifact:** [Motion to Dismiss](https://folio.openlegalstandard.org/R9Xkp4FqX83NG5ZI0CDfQ1k), [Evidence](https://folio.openlegalstandard.org/R9HuNkpWm24qMFuntuug6RB) · **Litigation Objectives:** [Litigation Burdens of Proof](https://folio.openlegalstandard.org/RDV74m3ydS2I72hZ88Mf1RX) · **Actor / Player:** [Plaintiff](https://folio.openlegalstandard.org/R9tyJmIM3Lx7OItGji5zPXN) |

</details>

<details>
<summary><strong>3. Law-firm know-how</strong>: a practice guide on expert witnesses</summary>

> *Trial Practice Field Guide*, ch. 7, "Expert Witnesses" (Lindqvist & Ober LLP internal know-how, 2025) (synthetic)
>
> On direct, ask open-ended questions and let your expert teach; jurors trust the witness, not the lawyer. The rules of evidence generally prohibit leading questions on direct but permit them on cross. At the opposing expert's deposition, lock in every opinion she plans to offer and every document she relied on. Do not argue with the expert at deposition; you will only educate her for trial. Close each topic by asking, "Have you now told me all the bases for that opinion?"

| Insight (proposition) | Source span | FOLIO tags |
|---|---|---|
| Ask your expert open-ended questions on direct and let the expert teach the jury. | "On direct, ask open-ended questions and let your expert teach" | **Event:** [Direct-Examination of Witness](https://folio.openlegalstandard.org/RDGR7PTYD8TltxEq0F8NGIR) · **Actor / Player:** [Testifying Expert Witness](https://folio.openlegalstandard.org/R7lbqYoeuZitiUJsrh5lYIB), [Jury](https://folio.openlegalstandard.org/R9pwejG33H0Y9mi74WzE2nb) |
| Leading questions are generally prohibited on direct and permitted on cross. | "generally prohibit leading questions on direct but permit them on cross" | **Deontic Specification:** [Prohibition](https://folio.openlegalstandard.org/RCqqI0SLTxsE8Z2rCu7KOXm), [Permission](https://folio.openlegalstandard.org/RCurUksxnjgPwYWpCSq0xPI) · **Event:** [Direct-Examination of Witness](https://folio.openlegalstandard.org/RDGR7PTYD8TltxEq0F8NGIR), [Cross-Examination of Witness](https://folio.openlegalstandard.org/RCz1SYWoNDDTDvPr0kSJBq) · **Legal Authorities:** [Federal Rules of Evidence](https://folio.openlegalstandard.org/R9sYB6Cf3u3k5hxxUFJyJHA) |
| At the opposing expert's deposition, lock in every opinion and every document relied on. | "lock in every opinion she plans to offer and every document she relied on" | **Event:** [Expert Witness Deposition](https://folio.openlegalstandard.org/RDvL7Pxoo5G3sPWI7IpBRgM) · **Actor / Player:** [Testifying Expert Witness](https://folio.openlegalstandard.org/R7lbqYoeuZitiUJsrh5lYIB) · **Service:** [Discovery Practice](https://folio.openlegalstandard.org/R9hR0S1zExtgPQTzV0LeyD3) |
| Do not argue with the opposing expert at deposition; it educates her for trial. | "Do not argue with the expert at deposition; you will only educate her for trial" | **Deontic Specification:** [Prohibition](https://folio.openlegalstandard.org/RCqqI0SLTxsE8Z2rCu7KOXm) · **Event:** [Expert Witness Deposition](https://folio.openlegalstandard.org/RDvL7Pxoo5G3sPWI7IpBRgM), [Jury Trial](https://folio.openlegalstandard.org/R9TOzhWvuxDJlWPJfg2UmhF) · **Actor / Player:** [Testifying Expert Witness](https://folio.openlegalstandard.org/R7lbqYoeuZitiUJsrh5lYIB) |
| Close each deposition topic with an exhaustion question. | "Have you now told me all the bases for that opinion?" | **Event:** [Deposition](https://folio.openlegalstandard.org/RCnTNVCQ1VndGxskbMoaLr8) · **Actor / Player:** [Witness](https://folio.openlegalstandard.org/R9tZFXPrXQJWHbqSgtCQxJF) · **Service:** [Discovery Practice](https://folio.openlegalstandard.org/R9hR0S1zExtgPQTzV0LeyD3) |

</details>

<details>
<summary><strong>4. Journal article</strong>: noncompetes, an exception, and promissory estoppel</summary>

> *Reliance Without a Bargain: Promissory Estoppel and the Mid-Employment Noncompete*, 41 Northland L. Rev. 233 (2025) (synthetic)
>
> Courts increasingly decline to enforce a noncompete agreement that an employee signed after starting work unless the employer supplied fresh consideration. A raise, a promotion, or access to new confidential information can serve; continued at-will employment often cannot. When the agreement fails for want of consideration, some employers turn to promissory estoppel, but that doctrine protects reliance on a promise, not an employer's expectation of restraint. This Article argues that courts should reject the estoppel route outright.

| Insight (proposition) | Source span | FOLIO tags |
|---|---|---|
| Courts decline to enforce a mid-employment noncompete unless the employer supplied fresh consideration. | "decline to enforce a noncompete agreement that an employee signed after starting work unless the employer supplied fresh consideration" | **Deontic Specification:** [Exception](https://folio.openlegalstandard.org/RCdJXw1Ml7DIBqmouWarZm2) · **Document / Artifact:** [Noncompete Agreement](https://folio.openlegalstandard.org/RuTiqSJ76kL8qUWS8cae3Z) · **Area of Law:** [Employment Law](https://folio.openlegalstandard.org/R7H5z7e67YZSVmjrNJ0r6rm) · **Actor / Player:** [Employee](https://folio.openlegalstandard.org/R8dLmng1TNW6uYIBHtkJuab), [Employer](https://folio.openlegalstandard.org/RsZxhuNFK33sHecLQ7WJdp) |
| A raise, a promotion, or access to new confidential information can support a mid-employment noncompete; continued at-will employment often cannot. | "continued at-will employment often cannot" | **Document / Artifact:** [Noncompete Agreement](https://folio.openlegalstandard.org/RuTiqSJ76kL8qUWS8cae3Z) · **Area of Law:** [Employment Law](https://folio.openlegalstandard.org/R7H5z7e67YZSVmjrNJ0r6rm), [Contract Law](https://folio.openlegalstandard.org/RCIPwpgRpMs1eVz4vPid0pV) · **Actor / Player:** [Employer](https://folio.openlegalstandard.org/RsZxhuNFK33sHecLQ7WJdp) |
| Promissory estoppel protects reliance on a promise, not an employer's expectation of restraint. | "protects reliance on a promise, not an employer's expectation of restraint" | **Litigation Objectives:** [Promissory Estoppel](https://folio.openlegalstandard.org/RDoqFy7w8Dr7R9MC1LSxNgv) · **Area of Law:** [Contract Law](https://folio.openlegalstandard.org/RCIPwpgRpMs1eVz4vPid0pV) · **Actor / Player:** [Employer](https://folio.openlegalstandard.org/RsZxhuNFK33sHecLQ7WJdp) · **Document / Artifact:** [Law Review Article](https://folio.openlegalstandard.org/RBg7sRYxsZKH1clvAIAQWhO) |

The article's closing thesis ("courts should reject the estoppel route") stays out of the table: it argues for a change in the law rather than stating the law, and the pipeline never judges which side wins.

</details>

<details>
<summary><strong>5. Statute</strong>: a data-breach notification law with duties, an exception, a penalty, a right, and a waiver ban</summary>

> Northland Consumer Data Breach Notification Act, Nland. Stat. § 325X.04 (2025) (synthetic)
>
> (a) A business that discovers a data breach shall notify each affected resident within 45 days after discovery. (b) The notice must describe the categories of personal information involved and the steps the resident can take to protect against identity theft. (c) A business may delay notice at the written request of a law enforcement agency, and a delay so requested does not violate subdivision (a). (d) A business that fails to give timely notice is subject to a civil penalty of up to $500 for each affected resident. (e) An affected resident may bring a civil action for damages caused by a violation of this section. (f) A business may not require a resident to waive any right under this section, and any such waiver is void. (g) An action under this section must be commenced within two years after the resident receives notice.

| Insight (proposition) | Source span | FOLIO tags |
|---|---|---|
| A business that discovers a data breach must notify each affected resident within 45 days after discovery. | "A business that discovers a data breach shall notify each affected resident within 45 days after discovery" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Event:** [Data Breach](https://folio.openlegalstandard.org/Raw03V8d0o2ILRa4VEpq4t) · **Document / Artifact:** [Notice](https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7) · **Area of Law:** [Privacy Law](https://folio.openlegalstandard.org/R8hJCf4Ih6iuFXsxeK7e6zU), [Consumer Protection Law](https://folio.openlegalstandard.org/RCovPJMo8mH3uZhlySLgWIa) · **Legal Authorities:** [Statutes](https://folio.openlegalstandard.org/RHagFJXtPsCCn5dbENWLNR) |
| The breach notice must describe the personal information involved and the steps residents can take against identity theft. | "describe the categories of personal information involved" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Document / Artifact:** [Notice](https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7), [Personal Information](https://folio.openlegalstandard.org/R8Ov4MbOJULZY0aLe1KoP3Z) · **Litigation Objectives:** [Impersonation / Identity Theft](https://folio.openlegalstandard.org/RFjY2mO804t9gJNy5Dn4P1) · **Area of Law:** [Privacy Law](https://folio.openlegalstandard.org/R8hJCf4Ih6iuFXsxeK7e6zU) |
| A business may delay notice at a law enforcement agency's written request without violating the 45-day duty. | "may delay notice at the written request of a law enforcement agency" | **Deontic Specification:** [Exception](https://folio.openlegalstandard.org/RCdJXw1Ml7DIBqmouWarZm2), [Permission](https://folio.openlegalstandard.org/RCurUksxnjgPwYWpCSq0xPI) · **Actor / Player:** [Law Enforcement](https://folio.openlegalstandard.org/RILQypXcjvqd1GxNIcqsb7) · **Event:** [Data Breach](https://folio.openlegalstandard.org/Raw03V8d0o2ILRa4VEpq4t) · **Document / Artifact:** [Notice](https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7) |
| A business that gives late notice faces a civil penalty of up to $500 per affected resident. | "subject to a civil penalty of up to $500 for each affected resident" | **Regulatory Objectives:** [Regulatory Penalty](https://folio.openlegalstandard.org/R6DLuG3VglXIci9EJ3MwAK) · **Deontic Specification:** [Violation](https://folio.openlegalstandard.org/RDsDXHKUsZoJfz87jnz7zjj) · **Document / Artifact:** [Notice](https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7) · **Area of Law:** [Privacy Law](https://folio.openlegalstandard.org/R8hJCf4Ih6iuFXsxeK7e6zU) · **Legal Authorities:** [Statutes](https://folio.openlegalstandard.org/RHagFJXtPsCCn5dbENWLNR) |
| An affected resident has a right to sue for damages caused by a violation. | "may bring a civil action for damages caused by a violation of this section" | **Deontic Specification:** [Right](https://folio.openlegalstandard.org/RmCCZU8GS7O8920pkDipw7), [Violation](https://folio.openlegalstandard.org/RDsDXHKUsZoJfz87jnz7zjj) · **Litigation Objectives:** [Private Right of Action](https://folio.openlegalstandard.org/R7oWyxtB6MtD5SutNOJyn6b), [Damages](https://folio.openlegalstandard.org/RCCv5YLoHUOm5AlqcCBzqGf) · **Area of Law:** [Consumer Protection Law](https://folio.openlegalstandard.org/RCovPJMo8mH3uZhlySLgWIa) |
| A business must not require a resident to waive rights under the section; any such waiver is void. | "may not require a resident to waive any right under this section, and any such waiver is void" | **Deontic Specification:** [Prohibition](https://folio.openlegalstandard.org/RCqqI0SLTxsE8Z2rCu7KOXm), [Waiver](https://folio.openlegalstandard.org/R9CBXdybYDztLBRNDNJl0W), [Right](https://folio.openlegalstandard.org/RmCCZU8GS7O8920pkDipw7) · **Area of Law:** [Consumer Protection Law](https://folio.openlegalstandard.org/RCovPJMo8mH3uZhlySLgWIa) · **Legal Authorities:** [Statutes](https://folio.openlegalstandard.org/RHagFJXtPsCCn5dbENWLNR) |
| A resident must sue within two years after receiving notice. | "must be commenced within two years after the resident receives notice" | **Litigation Objectives:** [Statute of Limitations](https://folio.openlegalstandard.org/RDKJ7nEqeDxNDRxI2Wqil1N), [Private Right of Action](https://folio.openlegalstandard.org/R7oWyxtB6MtD5SutNOJyn6b) · **Document / Artifact:** [Notice](https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7) · **Area of Law:** [Privacy Law](https://folio.openlegalstandard.org/R8hJCf4Ih6iuFXsxeK7e6zU) |

</details>

<details>
<summary><strong>6. Jury instruction</strong>: the duty of reasonable care, negligence, and direct cause</summary>

> Northland Civil Jury Instruction Guide, CIVJIG 25.10, "Negligence: Definition and Direct Cause" (synthetic)
>
> Every person has a duty to use reasonable care to avoid harming others. Negligence is the failure to use reasonable care. Reasonable care is the care a reasonable person would use in the same or similar circumstances. The plaintiff must prove by the greater weight of the evidence that the defendant was negligent and that the negligence was a direct cause of the harm. A direct cause is a cause that had a substantial part in bringing about the harm.

| Insight (proposition) | Source span | FOLIO tags |
|---|---|---|
| Every person owes a duty to use reasonable care to avoid harming others. | "Every person has a duty to use reasonable care to avoid harming others" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Litigation Objectives:** [Negligence](https://folio.openlegalstandard.org/R7nqxxlAfhYqqSA2UQ5UxpX) · **Area of Law:** [Personal Injury and Tort Law](https://folio.openlegalstandard.org/R7MK1XmyjtYxZKg8Iw4ZN4K) · **Document / Artifact:** [Jury Instructions](https://folio.openlegalstandard.org/RCaZrUbTpgbGRrwYk2keJES) |
| Negligence means failing to use the care a reasonable person would use in the same or similar circumstances. | "Negligence is the failure to use reasonable care" | **Deontic Specification:** [Violation](https://folio.openlegalstandard.org/RDsDXHKUsZoJfz87jnz7zjj) · **Litigation Objectives:** [Negligence](https://folio.openlegalstandard.org/R7nqxxlAfhYqqSA2UQ5UxpX) · **Area of Law:** [Personal Injury and Tort Law](https://folio.openlegalstandard.org/R7MK1XmyjtYxZKg8Iw4ZN4K) · **Document / Artifact:** [Jury Instructions](https://folio.openlegalstandard.org/RCaZrUbTpgbGRrwYk2keJES) |
| The plaintiff must prove negligence and direct cause by the greater weight of the evidence. | "must prove by the greater weight of the evidence" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Litigation Objectives:** [Preponderance of Evidence](https://folio.openlegalstandard.org/Ro7NzBFiq6eW3vKMpqpufQ) · **Actor / Player:** [Plaintiff](https://folio.openlegalstandard.org/R9tyJmIM3Lx7OItGji5zPXN), [Defendant](https://folio.openlegalstandard.org/RijIqw1HEfQF4ctjWUlgnq), [Jury](https://folio.openlegalstandard.org/R9pwejG33H0Y9mi74WzE2nb) |
| A direct cause played a substantial part in bringing about the harm. | "had a substantial part in bringing about the harm" | **Litigation Objectives:** [Proximate Cause](https://folio.openlegalstandard.org/R9urhXjf5qj2wZs4fVFCl7A), [Negligence](https://folio.openlegalstandard.org/R7nqxxlAfhYqqSA2UQ5UxpX) · **Event:** [Jury Trial](https://folio.openlegalstandard.org/R9TOzhWvuxDJlWPJfg2UmhF) · **Document / Artifact:** [Jury Instructions](https://folio.openlegalstandard.org/RCaZrUbTpgbGRrwYk2keJES) |

</details>

<details>
<summary><strong>7. Contract playbook</strong>: vendor duties, carve-outs, and penalty clauses in a SaaS agreement</summary>

> *Vendor SaaS Agreement Negotiation Playbook*, § 4, "Liability" (Fernhollow Analytics in-house legal team, 2025) (synthetic)
>
> Never accept a limitation of liability clause that caps the vendor's exposure below twelve months of fees. Carve out data breaches, confidentiality breaches, and indemnification obligations from the cap. Require the vendor to notify us of any security incident within 72 hours. A force majeure clause should not excuse the vendor's obligation to maintain backups and restore service. Push back on any late-payment penalty above 1% per month; a court may refuse to enforce a liquidated damages clause that operates as a penalty.

| Insight (proposition) | Source span | FOLIO tags |
|---|---|---|
| Never accept a liability cap below twelve months of fees. | "Never accept a limitation of liability clause that caps the vendor's exposure below twelve months of fees" | **Deontic Specification:** [Prohibition](https://folio.openlegalstandard.org/RCqqI0SLTxsE8Z2rCu7KOXm) · **Transactional Objectives:** [Limitation of Liability Clause](https://folio.openlegalstandard.org/RBukB9MGGdY4Kwx3b6itiwi) · **Document / Artifact:** [Software as a Service Agreement](https://folio.openlegalstandard.org/R8mchuGv5Xvl9V7trgYx6YB) · **Actor / Player:** [Licensor](https://folio.openlegalstandard.org/R8z4kx9VtFPf7lFSgoSi7Zt) |
| Exclude data breaches, confidentiality breaches, and indemnification obligations from the liability cap. | "Carve out data breaches, confidentiality breaches, and indemnification obligations from the cap" | **Deontic Specification:** [Exception](https://folio.openlegalstandard.org/RCdJXw1Ml7DIBqmouWarZm2) · **Transactional Objectives:** [Limitation of Liability Clause](https://folio.openlegalstandard.org/RBukB9MGGdY4Kwx3b6itiwi), [Data Breach Clause](https://folio.openlegalstandard.org/R8IQg7EUvdgPRcmPx8Sz8Au), [Confidentiality Clause](https://folio.openlegalstandard.org/RDOq8HJJl8YdcwBdCZmjlOW), [Indemnification Clause](https://folio.openlegalstandard.org/R9oz08cWJcI23x0nYU1h0it) · **Document / Artifact:** [Software as a Service Agreement](https://folio.openlegalstandard.org/R8mchuGv5Xvl9V7trgYx6YB) |
| The vendor must notify the customer of any security incident within 72 hours. | "Require the vendor to notify us of any security incident within 72 hours" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Event:** [Data Breach](https://folio.openlegalstandard.org/Raw03V8d0o2ILRa4VEpq4t) · **Document / Artifact:** [Notice](https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7), [Software as a Service Agreement](https://folio.openlegalstandard.org/R8mchuGv5Xvl9V7trgYx6YB) · **Actor / Player:** [Licensor](https://folio.openlegalstandard.org/R8z4kx9VtFPf7lFSgoSi7Zt) |
| Force majeure must not excuse the vendor's duty to maintain backups and restore service. | "should not excuse the vendor's obligation to maintain backups and restore service" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao), [Exception](https://folio.openlegalstandard.org/RCdJXw1Ml7DIBqmouWarZm2) · **Transactional Objectives:** [Force Majeure Clause](https://folio.openlegalstandard.org/R7mT3oM7UJnGCUIq15FYip5) · **Document / Artifact:** [Service Level Agreement](https://folio.openlegalstandard.org/RCoanW4qIyxyCW6i0RJ4M4N) |
| A court may refuse to enforce a liquidated damages clause that operates as a penalty. | "may refuse to enforce a liquidated damages clause that operates as a penalty" | **Transactional Objectives:** [Penalty Clause](https://folio.openlegalstandard.org/RCNKm9EnW4P2a7noaWhJg4j) · **Litigation Objectives:** [Liquidated Damages](https://folio.openlegalstandard.org/RBA52cjyeFhnjSJD6qnT1DM) · **Area of Law:** [Contract Law](https://folio.openlegalstandard.org/RCIPwpgRpMs1eVz4vPid0pV) · **Document / Artifact:** [Software as a Service Agreement](https://folio.openlegalstandard.org/R8mchuGv5Xvl9V7trgYx6YB) |

</details>

<details>
<summary><strong>8. CLE outline</strong>: duties in a corporate-representative deposition</summary>

> "Organizational Depositions in Practice," Northland CLE Litigation Institute, session outline, part II (synthetic)
>
> The noticing party must describe each topic with reasonable particularity; vague topics invite a designee who knows nothing. The organization has a duty to prepare its designee to testify about information reasonably available to it. Serve the deposition notice at least 30 days before the deposition so the organization can prepare. The designee testifies for the organization, so an "I don't know" can bind it at trial. Meet and confer on the topics before the deposition, and confirm the agreed scope in writing.

| Insight (proposition) | Source span | FOLIO tags |
|---|---|---|
| The noticing party must describe each deposition topic with reasonable particularity. | "must describe each topic with reasonable particularity" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Event:** [Corporate Representative Deposition](https://folio.openlegalstandard.org/R89iBjT2ujtCBRwmcKoTVJ) · **Document / Artifact:** [Notice](https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7) · **Legal Authorities:** [Rules of Civil Procedure](https://folio.openlegalstandard.org/RDaNIjG3Bz5mnMEssDHDHwf) |
| The organization must prepare its designee to testify about information reasonably available to it. | "has a duty to prepare its designee to testify about information reasonably available to it" | **Deontic Specification:** [Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao) · **Actor / Player:** [Corporate Representative Witness](https://folio.openlegalstandard.org/RBBifG8DRVUc0IVqvXZ2kex) · **Legal Entity:** [Corporation](https://folio.openlegalstandard.org/RDdgYa5ZbqVnS9aGrOwQu5h) · **Service:** [Corporate Representative Deposition Practice](https://folio.openlegalstandard.org/R3MdX1jnLm0lwZoaOurqTG) |
| Serve the deposition notice at least 30 days ahead so the organization can prepare. | "Serve the deposition notice at least 30 days before the deposition" | **Document / Artifact:** [Notice](https://folio.openlegalstandard.org/RB3FT9lFNQIjRnFIueLgCa7) · **Event:** [Corporate Representative Deposition](https://folio.openlegalstandard.org/R89iBjT2ujtCBRwmcKoTVJ) · **Service:** [Discovery Practice](https://folio.openlegalstandard.org/R9hR0S1zExtgPQTzV0LeyD3) |
| The designee speaks for the organization, so an "I don't know" can bind it at trial. | "The designee testifies for the organization" | **Deontic Specification:** [Authority](https://folio.openlegalstandard.org/R9ikrznaQwm4RUsMzP9KXFR) · **Actor / Player:** [Corporate Representative Witness](https://folio.openlegalstandard.org/RBBifG8DRVUc0IVqvXZ2kex) · **Legal Entity:** [Corporation](https://folio.openlegalstandard.org/RDdgYa5ZbqVnS9aGrOwQu5h) · **Event:** [Jury Trial](https://folio.openlegalstandard.org/R9TOzhWvuxDJlWPJfg2UmhF) |

</details>

Across all eight, the deontic tags mark duties ([Obligation](https://folio.openlegalstandard.org/RDtFkLR3v97fran5zQ3ugao)), permissions, prohibitions, exceptions, rights, waivers, violations, and authority, while [Regulatory Penalty](https://folio.openlegalstandard.org/R6DLuG3VglXIci9EJ3MwAK) and [Penalty Clause](https://folio.openlegalstandard.org/RCNKm9EnW4P2a7noaWhJg4j) mark penalties. The same insights also reach into areas of law, events, documents, actors, legal entities, legal authorities, forums, locations, and services.

## Who it's for

- **Ontologists and researchers** building FOLIO-aligned legal knowledge bases.
- **Application developers** who want legal propositions they can filter by duty, exception, penalty, area of law, forum, or actor.
- **AI engineers** wiring legal retrieval into RAG pipelines or agents; the JSON-LD export fits chunked retrieval.
- **Practitioners and educators** exploring which rules, duties, and exceptions a body of sources states.

## What you get

| Output | Use it for |
|---|---|
| OWL (RDF/XML), SHACL-validated | Reasoners, ontology editors, FOLIO alignment |
| Turtle | SPARQL stores, diffs, version control |
| JSON-LD | LLM retrieval and RAG chunking |
| HTML | Browsing insights and their tags in a browser |
| Markdown | Reading and sharing an outline |

One `export` command writes all five.

## Try it

**Demo.** A dev deployment serves a small synthetic corpus: <https://folio-insights.dev.openlegalstandard.org>.

**Requirements.** Python 3.11 or 3.12; Node.js 20+ only to rebuild the viewer (built assets ship with the repo); your own API key for an LLM provider (Anthropic, OpenAI, Google, or Ollama). The server never holds a shared key. Runs default to Google's `gemini-2.5-flash-lite`; pick another provider with `--llm-provider` or `FOLIO_INSIGHTS_LLM_PROVIDER`.

**Install.** FOLIO Insights still loads document ingestion and tabular mapping from two sibling repos, so clone all three side by side:

```bash
git clone https://github.com/alea-institute/folio-enrich.git
git clone https://github.com/alea-institute/folio-mapper.git
git clone https://github.com/alea-institute/folio-insights.git
cd folio-insights
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # add your key, e.g. GOOGLE_API_KEY or ANTHROPIC_API_KEY
folio-insights --version
```

**Run.**

```bash
folio-insights extract ./my-sources --corpus advocacy --output ./output   # extract insights, ground, and tag
folio-insights discover advocacy --output ./output                         # group insights by task (secondary)
folio-insights export advocacy --format owl,ttl,jsonld,html,md            # write all five formats
folio-insights serve --port 8742                                          # open the review viewer
```

`extract` and `discover` accept `--llm-provider`, `--llm-model`, and `--max-spend-usd`. Every command resumes from its last checkpoint. Run `folio-insights <command> --help` for thresholds and options.

## Review viewer

`folio-insights serve` opens a SvelteKit app backed by FastAPI. It walks one corpus through five steps: **Upload** (deduplicated by content hash), **Process** (live progress), **Discover** (task grouping and flagged contradictions), **Review** (approve insights, edit labels and tags, resolve contradictions), and **Export**. The viewer runs the same pipeline code as the CLI.

## How it works

1. **Extract and ground.** Structural heuristics split a document into passages; an LLM pulls out each insight (proposition) and anchors it to a verbatim source span.
2. **Tag.** The tagger attaches every FOLIO concept that applies, from any branch, and records each tag's branch. The pinned [folio-resolve](https://github.com/damienriehl/folio-resolve) library turns labels into FOLIO IRIs deterministically. An LLM judge may reject or downgrade a tag, but no model ever writes an IRI.
3. **Map to OWL.** Insights become RDF with FOLIO links and provenance.
4. **Validate and export.** SHACL checks the graph before export.

The pipeline also assigns each insight a coarse type (`advice`, `principle`, `procedural_rule`, `citation`, or `pitfall`, from the `KnowledgeType` enum in [`knowledge_unit.py`](src/folio_insights/models/knowledge_unit.py)), and `discover` groups insights under advocacy tasks and flags contradictions between sources. Both stay secondary to the FOLIO tags.

## Status

**v1.0 (2026-04-04)** shipped the pipeline, CLI, and viewer above.

**v2.0, "shards as axioms" (in progress),** turns each unit into a signed, versioned *shard* that a community can review, cite, fork, and supersede. Landed on `master`: a pyoxigraph store with SHACL checks on every write; content hashing and stable IRIs; `did:key`, `did:web`, and `did:plc` reviewer identities with signed attestations; a governance lifecycle; valid-time supersession; a provider-neutral LLM layer with a spend cap; a durable job queue; a seed kernel of Latin legal maxims; and a gated shard minter. [`PHILOSOPHY.md`](PHILOSOPHY.md) explains the design; [`PRD-v2.0-draft-2.md`](PRD-v2.0-draft-2.md) specifies it.

**Extraction quality: not yet validated on a real corpus.** The examples above show the target, not measured output. In July 2026, a test run on a legal treatise found invented units and about 90% of 2,226 FOLIO tags pointing at the wrong concept. Two fixes have landed since: deterministic IRI resolution (July 2026) and a shard minter that refuses any unit whose text it cannot anchor in the source (October 2026). No real corpus has yet cleared the publishing bar (a 0.80 score on the extraction-quality rubric). Until one does, treat every shard as a hypothesis.

**Planned.** An annotation workbench will show source text with FOLIO tags overlaid, so reviewers can mark each tag correct, weak, or wrong and flag concepts the tagger missed. Mockups live in [`docs/design/review-ui/`](docs/design/review-ui/).

## More commands

Beyond the core four: `verify-iris` re-mints every stored shard IRI and reports drift, and v2.0 adds the groups `mint`, `rubric`, `kernel`, `graph`, `query`, `validate`, `framework`, `bfo`, `polysemy`, `did`, `governance`, `corpus`, `storage`, `proposals`, `bench`, `api`, `bridge-ingest`, and `bridge-status`. Each group loads its heavy dependencies lazily.

### Corpus review signatures

`FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISION_CORPORA='["corpus-a","corpus-b"]'`
requires registered review signatures for those corpus IDs. The default is an empty
list. `FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS=1` still requires signatures for every
corpus; a corpus selection cannot relax that requirement. Both settings use the
existing public reviewer registry, `FOLIO_INSIGHTS_DECISION_SIGNERS_FILE`. Missing or
unusable required registration refuses the decision before any write. Operator
authentication and decision authorship remain separate checks.

## Deploy

The dev site runs `Dockerfile.web` on Coolify: one FastAPI service that also serves the built viewer, with `/health` as its healthcheck. LLM features take each user's own key. Details: [`docs/deploying.md`](docs/deploying.md).

## Project layout

```
src/folio_insights/   pipeline, CLI, and the v2.0 modules (shards, governance, identity, storage, minting, ...)
api/                  FastAPI backend for the viewer
viewer/               SvelteKit review viewer
docs/                 plans, evidence packs, rubrics, design mockups, handoffs
tests/                pytest suite
.planning/            legacy GSD planning record
```

## Contributing

Open an issue before large changes; send small fixes and doc edits as pull requests. Run the fast suite (about 3,500 tests) with `pytest -m "not slow and not gate5"`; integration tests need folio-enrich checked out. The repo has no GitHub Actions yet, so attach your local test results to each PR. Changes to confidence thresholds, gating, or tagging paths need a written rationale, because downstream consumers depend on them.

## Out of scope

FOLIO Insights does not offer legal advice, judge legal merit, run in real time, rewrite source text, or process non-English source text.

## License

MIT; see [LICENSE](LICENSE). Third-party licenses: [THIRD-PARTY.md](THIRD-PARTY.md). FOLIO and BFO carry CC-BY 4.0.

Copyright © Damien Riehl and ALEA Institute.
