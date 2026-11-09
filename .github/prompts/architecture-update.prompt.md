---
description: 'Update architecture docs and diagrams after a change, keeping them consistent with the code'
agent: 'architecture'
---
# Update architecture documentation (UPDATE mode)

Mode: UPDATE. Edit documentation only unless told otherwise.
Change and documents to update: ${input:change:What changed, and which doc/feature/model group to update}

0. Output path: ${input:path:Optional exact path; leave empty to follow docs/ai-team/documentation-map.md}. State the path you choose and why before writing.
1. Read the existing document and the implementation it describes.
2. Run an impact scan: search docs and code for each changed symbol, model, endpoint, event, and constraint.
3. Make targeted edits (no whole-document rewrites); synchronize diagrams, relationships, constraints,
   links, and terminology; check for contradictions with unaffected documents.
4. Summarize what changed and any follow-up work; report validation as passed, failed, or not run.
