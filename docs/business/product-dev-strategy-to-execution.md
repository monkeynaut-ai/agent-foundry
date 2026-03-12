# 730 Alchemy Product Strategy Session

## Context

Agent Foundry is a platform for agentic AI systems. Its function is to accelerate development of highly capable agentic systems in any domain. We are using Agent Foundry to build systems for internal use (ops, strategy, engineering, decision support, knowledge management, etc) and for external use (software products and services). Archipelago (autonomous software engineering) is the first system built on Agent Foundry.

The user provided a document describing a system to implement using Agent Foundry, covering three sections: core components of a software product strategy, tactical concerns of each strategic component, and teams required to materialize tactical concerns.

---

## Core Components of a Software Product Strategy

1. **Vision**

    Clear description of the long-term change the product aims to create. Aligns teams around the ultimate purpose and direction.

2. **Target Users / Customer Segments**

    Specific groups the product is built for. Defines whose problems matter most and prevents building for "everyone."

3. **Problem Definition**

    The high-value user problems the product will solve. Must be concrete, validated, and prioritized.

4. **Value Proposition**

    Why the product is meaningfully better for users than alternatives. Articulates the core benefit delivered.

5. **Market Positioning**

    How the product is positioned relative to competitors and substitutes. Defines differentiation and strategic advantage.

6. **Product Scope**

    The categories of capabilities the product will and will not include. Establishes strategic boundaries to avoid scope creep.

7. **Strategic Pillars / Themes**

    A small set of guiding priorities that drive roadmap decisions (e.g., automation, collaboration, performance).

8. **Business Model**

    How the product creates economic value: pricing model, monetization approach, and revenue mechanics.

9. **Go-to-Market Strategy**

    How the product reaches and acquires users: distribution channels, onboarding strategy, partnerships, and marketing.

10. **Roadmap Direction**

    High-level sequence of initiatives aligned to the strategy (not just features). Shows how the strategy will be executed over time.

11. **Success Metrics**

    Measurable indicators of success such as adoption, retention, engagement, or revenue.

12. **Strategic Constraints & Tradeoffs**

    Explicit choices about what will be deprioritized due to resources, technology, or market realities.

## Tactical Concerns of each Strategic Component

| Strategic Component | Tactical Concerns |
| --- | --- |
| **Vision** | Internal communication artifacts, strategy docs, alignment meetings, storytelling in leadership presentations, decision filters for roadmap prioritization. |
| **Target Users / Customer Segments** | User research interviews, personas, segmentation models, CRM tagging, cohort analysis, targeted onboarding flows. |
| **Problem Definition** | Problem statements, user journey mapping, support-ticket analysis, usability testing, problem validation experiments. |
| **Value Proposition** | Landing page messaging, feature packaging, onboarding copy, demo scripts, product marketing assets, competitive messaging. |
| **Market Positioning** | Competitive analysis, positioning statements, pricing comparison pages, sales battlecards, messaging frameworks. |
| **Product Scope** | Feature backlog boundaries, architecture constraints, product requirement documents (PRDs), prioritization frameworks (RICE, MoSCoW). |
| **Strategic Pillars / Themes** | Quarterly initiatives, epics in backlog, roadmap grouping, OKR alignment, cross-team project planning. |
| **Business Model** | Pricing tiers, billing implementation, subscription logic, packaging of features, trial flows, revenue analytics dashboards. |
| **Go-to-Market Strategy** | Channel campaigns, sales enablement materials, onboarding funnels, launch plans, partnership agreements, marketing experiments. |
| **Roadmap Direction** | Sprint planning, milestone definitions, release schedules, backlog grooming, cross-team dependency tracking. |
| **Success Metrics** | Analytics instrumentation, dashboards, A/B testing frameworks, KPI reviews, growth experiments. |
| **Strategic Constraints & Tradeoffs** | Resource allocation decisions, build vs. buy evaluations, technical debt prioritization, hiring plans, infrastructure limits. |

## Teams Required to Materialize the Tactical Concerns

1. **Product Management Team** — Owns product vision translation into strategy, roadmap direction, prioritization frameworks, and product requirement definitions.
2. **User Research Team** — Conducts interviews, usability studies, surveys, and behavioral research to validate user segments and problem definitions.
3. **Design / UX Team** — Produces user journeys, interaction design, UI systems, prototypes, and usability improvements tied to the value proposition.
4. **Engineering / Development Team** — Builds and maintains the product, implements features, architecture, infrastructure, and technical integrations.
5. **Data & Analytics Team** — Implements instrumentation, builds dashboards, analyzes user behavior, measures product success metrics, and runs experiments.
6. **Product Marketing Team** — Defines positioning, messaging, value proposition articulation, and launch communication for the product.
7. **Growth / Acquisition Team** — Designs and runs user acquisition experiments, marketing channels, funnels, and optimization of onboarding and conversion.
8. **Sales Team** — Handles enterprise or transactional selling, develops sales materials, manages deals, and provides customer feedback loops.
9. **Customer Success Team** — Ensures adoption, onboarding success, retention, and expansion for existing customers.
10. **Customer Support Team** — Handles support tickets, user issues, troubleshooting, and feeds product insights back into the organization.
11. **Pricing & Monetization Team** — Designs pricing models, packaging, subscription logic, and evaluates monetization performance.
12. **Partnerships & Business Development Team** — Establishes strategic partnerships, integrations, distribution deals, and ecosystem relationships.
13. **Platform / Infrastructure Team** — Manages cloud infrastructure, reliability, scalability, deployment systems, and core technical services.
14. **Security & Compliance Team** — Ensures data security, regulatory compliance, risk management, and operational security practices.
15. **Program / Delivery Management Team** — Coordinates cross-team initiatives, milestone planning, release schedules, and dependency management.
16. **Operations / RevOps Team** — Maintains CRM systems, operational workflows, sales/marketing tooling, and revenue operations infrastructure.

---

## Analysis: Initial Approaches

Four paths were considered for how to attack building a system of systems on Agent Foundry to support every team:

### Path A: Capability Taxonomy

Map every tactical concern across all 16 teams to a set of **primitive capability types** — research/synthesis, document generation, structured analysis, data pipeline, optimization loop, human-in-the-loop review, etc. This reveals clusters: competitive analysis (Sales), positioning statements (Product Marketing), and battlecards (Sales) all share a "research -> synthesize -> format" pattern. The output is a taxonomy that tells us exactly what to build into Agent Foundry as reusable capabilities vs. what stays product-level.

**Tradeoff**: Planning work, no running code, but prevents building the wrong abstractions.

### Path B: Vertical Slice — Pick One Team

Choose one team, build a complete agentic system for their tactical concerns end-to-end. **Product Marketing** is a strong candidate — its outputs (positioning statements, messaging frameworks, competitive messaging, launch comms) are well-defined documents, current LLMs are strong here, and the inputs (strategy, user segments, competitive landscape) are structured. Engineering is another option but Archipelago already covers much of it.

**Tradeoff**: Fast learning, running code, but risks building narrow abstractions that don't generalize.

### Path C: Shared Knowledge Foundation

Every team reads from and writes to the **product strategy as a shared knowledge structure**. Before building any team-specific system, design the common data model — how strategy components, tactical artifacts, and team outputs relate to each other. This becomes the connective tissue: when Product Marketing produces a positioning statement, Product Management sees it inform roadmap decisions, and Sales picks it up for battlecards. This is the "system of systems" architecture problem.

**Tradeoff**: Foundational but abstract. Gets the architecture right before building, but takes longer to show value.

### Path D: Low-Hanging Fruit

Cherry-pick 3-4 tactical concerns where AI is strongest today and Agent Foundry's existing patterns (registry, plan, compile, execute with gates) apply directly:

- **Competitive analysis** — research + synthesis pipeline
- **Sales battlecards** — structured generation from positioning + competitive data
- **Support ticket analysis** — classification + insight extraction + routing to product teams
- **Persona generation** — synthesis from user research data

Build these as standalone capabilities, then notice the patterns that emerge.

**Tradeoff**: Quick wins, tangible value, but risks ad-hoc architecture.

**Initial recommendation**: Paths A then B — spend one session on the capability taxonomy to understand the shape of the problem, then pick a team for vertical implementation with that map in hand. Or Path D to get something running fastest.

---

## Business Model Context

730 Alchemy aims to **partner with founders that need to get MVPs to market quickly**. The strategy:

- Reduce time to get MVPs out
- Have MVPs wired to collect high-value signals (what to change, what to lean into)
- Understand how to leverage AI and agentic systems in software to address needs

**Key hypothesis**: Markets will have a greater need for companies that know how to leverage AI (730 Alchemy) than for companies that have tools for autonomous software development (also 730 Alchemy, but that's a hidden lever).

**Multiplier logic**: If MVP time is significantly reduced, the number of MVPs (and business partners) per month increases, increasing the chance of striking gold.

**Timeline clarification**: Partners will not be pursued for at least 6 weeks. What gets built in this space will also serve as a way to **attract partners** — it's both tooling and demonstration.

---

## Revised Analysis with Business Model

### The Engagement Pipeline

Each founder partnership is roughly:

1. **Understand their strategy** (they bring vision + problem + users; fill gaps fast)
2. **Scope an MVP** (product scope, feature set, architecture)
3. **Build it fast** (Archipelago territory)
4. **Wire signal collection** (instrumentation, analytics, feedback loops)
5. **Interpret signals and iterate** (what to change, what to lean into)
6. **Identify AI leverage points** in their specific domain

### Revised Paths

#### Path 1: The Engagement Accelerator Pipeline

Build the end-to-end engagement workflow as an Agent Foundry system:

- **Strategy intake agent**: Takes a founder conversation (or rough pitch) -> produces a structured product strategy (the 12 components, filled to MVP-appropriate depth)
- **MVP scoping agent**: Strategy -> minimal feature set, architecture decisions, tech stack, what to cut
- **Archipelago**: Spec -> working code (already exists)
- **Signal wiring agent**: Given the MVP's problem definition + success metrics -> generates instrumentation plan, analytics events, feedback collection points
- **Signal interpretation agent**: Collected data -> actionable insights

#### Path 2: Strategy-to-Spec Fast Path

The bottleneck is likely not coding (Archipelago handles that) — it's the messy front end: understanding the founder's vision, structuring it, scoping the MVP, and making crisp decisions about what to build. Build the agents that compress **weeks of strategy/scoping into days**:

- Founder dumps rough pitch, competitive landscape, target users
- System produces structured strategy, identifies gaps, asks targeted questions
- Produces MVP scope with clear boundaries
- Generates feature specs ready for Archipelago

This is the highest-leverage piece because it's the part that currently requires human expertise for every engagement. Automating it (or augmenting it heavily) is what lets you scale partners per month.

#### Path 3: Signal Collection as a Platform Capability

Make "wired for signals from day one" a first-class Agent Foundry capability. Every MVP Archipelago builds comes pre-instrumented:

- Analytics events baked into generated code
- Feedback collection UI components as standard capabilities
- Dashboard generation from success metrics
- Automated signal interpretation that feeds back into the strategy

This is differentiating — most MVPs ship blind. Yours ship with eyes open. And it's a retention mechanism: founders stay because you're the ones who can read the signals and act on them.

### Recommendation

**Path 2 is the highest-leverage starting point:**

- Archipelago already covers build. Signal collection (Path 3) matters but is downstream.
- Path 1 is the full vision but too big to start with.
- Path 2 directly attacks the **throughput bottleneck**: the strategy-to-spec phase that currently requires human brain on every deal.
- It produces artifacts (structured strategies, MVP scopes, feature specs) that **feed directly into Archipelago** — so you get end-to-end value immediately.
- The capability taxonomy (Path A) happens naturally as you design what the strategy intake and MVP scoping agents need to do.

### The 6-Week Framing

What gets built needs to be a **visible, end-to-end experience** that a founder can witness and immediately understand: "these people can take my idea and move faster than anyone else."

The chain needed:

1. **Strategy intake -> structured strategy** (the front door — what founders interact with first)
2. **Strategy -> MVP scope -> feature specs** (decision-making compression)
3. **Specs -> working code** (Archipelago — already exists)
4. **Signal collection wired in** (the "comes with eyes open" differentiator)

The whole chain needs to be demonstrable in 6 weeks. Not production-hardened, but real enough to run a founder's idea through and produce something tangible.

**Week-scale sketch:**
- Get the strategy intake agent producing structured output from rough input
- Get MVP scoping producing feature sets from that output
- Connect to Archipelago for code generation
- Add basic signal collection as a standard capability

**Start with the Strategy Intake System** — it's the front door of the demo, it's where founders engage first, and it sets the tone for everything downstream.
