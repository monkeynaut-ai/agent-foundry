# Engineering Documentation Management

## Problem

Specifications that combine design intent with implementation planning become misleading after work completes. The work always diverges from the plan. Without a closure process, specs accumulate post-hoc notes, contradictions pile up, and nobody can tell which parts describe reality vs. aspiration.

This was observed directly in the Agent Foundry docs: 50KB+ specs mixing completed and unrealized work, protocol designs superseded mid-implementation with only a bolted-on note acknowledging the change, and testing journals indistinguishable from authoritative reference.

## Industry Landscape

### What top companies do

**Google**: Design docs are treated as "the most accessible entry point to learn about the thinking that guided the creation" of a system. During active development, updating is expected. After shipping, updates become inconsistent. The practical reality is that design docs become read-only historical artifacts consulted for "why did we do this?" but not kept current. No formal closure process. Google's Malte Ubl acknowledges that design docs "tend to get out of sync with reality over time" and organizations end up with "an eventual state more akin to the US constitution with a bunch of amendments."

**Stripe**: Uses templates for PRDs, implementation reviews, and launch reviews as distinct document types. A feature isn't shipped until its documentation is written, reviewed, and published. Design docs use "gavel blocks" where stakeholders check off that they've reviewed. The key insight is that Stripe uses **separate document types for separate lifecycle phases** rather than trying to evolve one document through multiple phases.

**Amazon**: Six-pagers are meeting tools written to drive a decision. Once the decision is made, the doc's job is done. No public information about post-implementation lifecycle.

**Anthropic**: Fast-paced, shorter docs, empirical results emphasized. Relatively easy to start a new initiative given a short doc with a strong argument. No formal post-implementation doc lifecycle described.

### What the literature recommends

**RFC-as-frozen-artifact**: When implementation begins, the RFC goes to readonly and stays for future context. The rationale: the RFC is a decision tool, not living documentation. Once the decision is made and work begins, the code becomes the source of truth.

**ADR (Architecture Decision Records)**: Instead of updating the original design doc, capture key decisions as lightweight ADRs that persist independently. Decisions outlive the documents that produced them.

**Lessons learned integration**: Organizations that systematically capture lessons learned reduce repeated mistakes by ~25%. The key finding: lessons should be captured continuously during the project, not just at the end, because end-of-project retrospectives suffer from recency bias and fatigue.

**Document lifecycle management**: The formal framework is Create, Review, Approve, Distribute, Maintain, Archive, Dispose. Most engineering organizations skip everything after Distribute.

### The universal gap

Almost no public engineering literature addresses what happens to design docs after implementation. The Pragmatic Engineer, Google's design doc guide, Stripe's process, Amazon's 6-pagers -- all focus on creation and review. Post-implementation, the guidance stops. The actual industry practice is: nobody updates design docs post-ship.

## Proposed Process: Spec Closure

When a spec's work is merged to main (the trigger), perform the following steps.

### Step 0: Update the spec during work when the design diverges

This happens before closure, during implementation. When the design materially diverges from the spec (e.g., switching from PTY to headless adapter), add a dated "Design Divergence" note at the point of divergence. This prevents the worst contradictions from accumulating silently.

### Step 1: Gap analysis

Compare completed work against the spec's stated objectives, acceptance criteria, and PR/commit slices. Produce a short gap report:
- What was completed as specified
- What was completed but diverged from spec (and how)
- What was not completed

This step informs all subsequent steps.

### Step 2: Route incomplete work

For anything identified as not completed in the gap analysis:
- Strip it from the spec into a separate document (e.g., `deferred-from-<spec-name>.md`)
- Create tracked task items for each piece of deferred work
- Include enough context in the task for someone to pick it up without reading the full original spec

### Step 3: Extract lessons learned

Review the spec and the implementation experience for insights that should persist:
- Design decisions that worked well or poorly
- Assumptions that proved wrong
- Patterns discovered during implementation
- Failure modes encountered

Route these to an appropriate knowledge store. In the Agent Foundry context, this means CLAUDE.md (for behavioral guidance), memory files (for project context), or architecture decision records (for design rationale). Avoid standalone "lessons learned" documents that become write-only.

### Step 4: Extract reference material

Identify any content in the spec that describes how an external system works (not your system) or that serves as a reusable reference. Examples: CLI flag inventories, protocol message schemas, API surface area catalogs.

Move this content to the appropriate reference location. What remains in the spec should describe only the design decisions and implementation plan for your system.

### Step 5: Archive the spec

Move the spec to an `archived/` folder. Add a header note with:
- Date archived
- Summary of what was built
- Pointer to the current authoritative documentation (if any)
- Pointer to deferred work document (if any)

Do not delete specs. They are useful for "why did we build it this way?" questions months later.

## Design Principles

**Single trigger**: The process fires when work is merged, not "when we get around to it." If the trigger is fuzzy, the process won't happen under deadline pressure.

**Specs are decision tools, not living documentation**: A spec's primary job is to align people before building. After the work ships, the code is the source of truth. The archived spec preserves design intent and rationale.

**Separate documents for separate lifecycle phases**: Following Stripe's pattern, don't try to evolve one document through multiple phases. A spec, an implementation plan, a gap report, and reference documentation are different document types serving different audiences at different times.

**Lessons land where they'll be read**: Lessons extracted during closure must land in a location that's consulted during future work (CLAUDE.md, memory, ADRs), not in a standalone document that nobody opens.

**Automate or it won't survive**: The process should be implemented as a Claude Code skill (`/close-spec`) or at minimum a checklist in CLAUDE.md. Processes that live only in someone's head get skipped under pressure.

## Sources

- [Design Docs at Google](https://www.industrialempathy.com/posts/design-docs-at-google/) -- Malte Ubl on Google's design doc practices, post-implementation drift, and template structure
- [Engineering Planning with RFCs, Design Documents and ADRs](https://newsletter.pragmaticengineer.com/p/rfcs-and-design-docs) -- Pragmatic Engineer on RFC lifecycle and the frozen-artifact approach
- [Docs culture at Amazon, Google, Meta, Stripe, Anthropic](https://twocentspm.substack.com/p/docs-culture-at-amazon-google-and) -- Cross-company comparison of documentation practices
- [Inside Stripe's Engineering Culture: Part 2](https://newsletter.pragmaticengineer.com/p/stripe-part-2) -- Stripe's template-driven documentation, gavel blocks, and launch review process
- [Companies Using RFCs or Design Docs](https://blog.pragmaticengineer.com/rfcs-and-design-docs/) -- Survey of RFC/design doc practices across engineering organizations
- [RFC Driven Development](https://engineering-management.space/post/rfc-driven-development/) -- RFC-as-frozen-artifact pattern and post-implementation readonly approach
- [Lessons Learned: Complete Framework](https://www.luckiwi.com/en/blog/article/lessons-learned/) -- Research showing 25% reduction in repeated mistakes with systematic lessons capture
- [Document Lifecycle Management](https://document360.com/blog/document-lifecycle/) -- Formal Create-Review-Approve-Distribute-Maintain-Archive-Dispose framework
