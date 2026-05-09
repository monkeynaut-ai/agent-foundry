# Agent Foundry Vision

## Context

LLMs and agentic systems are new. Best practices for using LLMs, designing agent architectures, and building products around them are being discovered — not inherited from prior art. Our understanding of the problems and frictions is evolving. This document captures what we believe today, how we think builders experience the platform, and what we're still figuring out. It is a living document; sections will be revised as we learn.

## Who This Is For

Builders who want to rapidly create, and continually improve, high-quality agentic systems that bend the value curve up — accelerating how fast they deliver value through AI and AI agents.

These builders are optimizing for:

- Speed from idea to working system
- Iteration velocity — change something, see the outcome, learn
- Quality that doesn't require a second "hardening" project after the prototype

## MOTIVATIONS --  ++ What We Believe

Convictions strong enough to build on. Each is stated with its rationale. All are subject to revision as we learn.

To Add:

- bring the singularity into existence and play in its tides
- prepare for inevitable increase in llm-related costs. Build mitigation into agent foundry
  - mitigate outages with model/provider switch logic option ... may duplicate existing offering
- complete control over agent execution environment
- always be capturing data
  - an advantage of running claude code in a container and running it headless with streaming output optiond
- knowledge is a strategic asset. Accelerate learning and acceleration. Also, always look for ways to learn
  - use agent stream out (assistant messages) to gauge fidelity of claude code (agent) to its instructions
  - [OSS candidate?] create reusable tools to assist/empower this type of assessment (e.g clever uses of jq and ... ?)

```
  Tool-use distribution (which tools did it actually use vs. what we told it to prefer):
jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "tool_use") | .name' stream.jsonl | sort | uniq -c | sort -rn
Answers: Did it use Task (Explore delegation) much, or did it grep/read directly? Did it call StructuredOutput once per turn? Did it touch LSP at all?

Event-type distribution:
jq -r '.type' stream.jsonl | sort | uniq -c
Answers: How many turns? How many assistant vs user (tool-result) messages?

Stop reasons per assistant message:
jq -r 'select(.type == "assistant") | .message.stop_reason' stream.jsonl | sort | uniq -c
Answers: How did turns terminate? tool_use = normal mid-turn; end_turn = agent chose to stop; max_tokens = bad.

Tier 2 — text-only slice (~30–50K, lands cleanly in context)

Strip tool payloads (the bulk of the 762K), keep just the agent's prose:
jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "text") | .text' stream.jsonl > /tmp/designer-thinking.txt
wc -c /tmp/designer-thinking.txt  # likely < 50K
This is the agent's "thinking aloud" — you can read it straight to judge: did it plan before acting? Did it write an investigation summary before drafting (per our
instructions)? Did it cite scope boundaries / assumptions explicitly when shaping the design? Did it ever mention "clarification" or "risk" in the framing we taught
it?
```

## Principles (better heading?)

- hide LangChain, LangGraph, MLflow
- primitives to simplify defining topology
- composability
- strict typing
- standardize tool calling - correctly interpret tool calls, and argument structure, from any model

<!-- Format: **Belief.** Rationale. -->

## Builder Journey

How a builder experiences Agent Foundry over time. This section is the lens for evaluating everything else — if a belief, a capability, or a design rule doesn't show up in the builder's actual experience, it's either aspirational or wrong.

### First Hour

<!-- What does a builder get out of the box? What can they stand up immediately? -->

### First Week

<!-- How do they extend, customize, experiment? What do they learn about the platform? -->

### Ongoing

<!-- How does the platform support continuous improvement? What gets better over time? -->

## Capability Rings

Each ring depends on the one inside it. For each: what exists today, what's next, and what's speculative.

### Core

The execution engine — primitives, compilation, state management, typing.

<!-- Exists: ... -->
<!-- Next: ... -->
<!-- Speculative: ... -->

### Platform Services

Value-added capabilities the platform provides to builders — memory, knowledge, data sources, communication channels.

<!-- Exists: ... -->
<!-- Next: ... -->
<!-- Speculative: ... -->

### Product Surface

What end-users of products built on Agent Foundry see — UI widgets per node, admin and monitoring UX.

<!-- Exists: ... -->
<!-- Next: ... -->
<!-- Speculative: ... -->

### Ecosystem

Extension points, registries, community-contributed primitives and agents.

<!-- Exists: ... -->
<!-- Next: ... -->
<!-- Speculative: ... -->

## Design Philosophy

Decision rules and tradeoffs that guide choices when the path isn't obvious.

<!-- Format: **Rule.** When it applies. Why. -->

## Ideas We Are Pondering

Frontiers we're actively exploring. Not gaps to fill — questions to investigate. As we learn, items here may become beliefs, capabilities, or get discarded.

- dynamic agent instructions, customize for each job
- enable simple and reactive changes to domain models
  - customized instructions per run, context size control, targeted focus, less rework (noise to correct later)
  - mitigation for future increases in llm inference costs

<!-- Format: **Question or idea.** What we're curious about. What would change if we found an answer. -->
