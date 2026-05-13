# Recall-Tool Protocol: Fixed Lookup vs. Disambiguation

**Status:** Design pattern reference (no current tool implements both halves; document up-front so V2 tools follow it).

When adding a tool that looks up an entity (a customer, a policy, a
prior case) by user-supplied description, choose one of two response
protocols up front — they have different LLM consumption semantics
and mixing them silently in one tool causes confusing UX.

## Protocol A — Fixed Lookup

The tool returns **at most one match** (or empty). Use when the
caller's intent unambiguously names a single entity.

### Response shape

    {
      "ok": true,
      "match": null | { "id": ..., "name": ..., ... }
    }

### When to use

- "Pull up case 12345" — id is unique.
- "Show me Zhang's policy" — when the user has already disambiguated
  in a prior turn and the tool now has the resolved id.
- "Get the latest annual report" — singleton by definition.

## Protocol B — Disambiguation (candidate list)

The tool returns **N candidates** when the description matches
multiple entities. The LLM is responsible for asking the user to pick
one, then re-invoking the tool with the resolved id in the next turn.

### Response shape

    {
      "ok": true,
      "candidates": [
        { "id": ..., "name": ..., "summary": "...one-line hint..." },
        ...
      ],
      "disambiguation_needed": true
    }

When the description matches exactly one entity, the tool may
collapse to `"candidates": [the_one]` with `"disambiguation_needed":
false` — the LLM-side prompt handles both branches identically.

### When to use

- "That case from last week about the property dispute" — fuzzy.
- "The customer who works in fintech" — likely matches several.
- "Find me a similar past audit decision" — by definition multi-match.

## Why not one polymorphic tool

Mixing A and B in one tool forces the LLM to inspect the response
shape every turn. Empirically that doubles the rate of one-turn-too-
late confirmations ("oh actually I meant the other one"). Splitting
makes each tool's contract one-line in the LLM tool description, and
the LLM uses the right one based on the user's phrasing.

## doc-qa today

`search_documents` is a **chunk-recall tool**, not an entity-recall
tool — it returns the top-K most-relevant chunks regardless of
ambiguity, and downstream rerank + LLM prose synthesis handles the
"which chunk matters" decision. It is **not** an instance of either
protocol; it is the document-level cousin.

When V2 adds entity-level tools (e.g. `recall_similar_case`,
`recall_policy_clause`), pick A or B per the above and document
which in the tool's `description` field.
