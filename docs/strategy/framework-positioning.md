# Agent Foundry Framework Positioning
Agent Foundry is a typed, boundary-enforced framework for declaring and running
agentic systems. Builders compose processes from declared constructs, validate
state boundaries, and run them through adapter seams for workflow engines, agent
harnesses, model providers, tools, and observability backends.

Those seams are the long-term portability strategy. The adapter ecosystem is
still a work in progress: Agent Foundry provides the core abstractions and
initial integrations, while broader backend and provider support still needs to
be built and validated.
## Who is Agent Foundry for
Agent Foundry is for builders and teams experimenting with how to build effective agentic systems.

We still have a lot to learn about AI, agents, and agentic systems. The best way to learn is through experimentation, and the easier it is to experiment the more we can learn. Agent Foundry simplifies experimenting with things such as: which instructions work, how memory should be managed, what topology fits a use case, which models or providers are worth their cost, where humans should stay in the loop, and how agent behavior should be evaluated.

Agent Foundry is for people who want to run those experiments without rebuilding the whole system each time. It gives them typed process boundaries, declared constructs, and adapter seams so they can change prompts, models, tools, memory strategies, agent harnesses, and execution backends while preserving a stable frame for comparison, measurement, and reuse.
## Core value
The process contract stays stable while models, prompts, tools, memory strategies, agent runtimes, execution backends, and observability systems change. Agent Foundry owns the portable contract layer; backends and agent frameworks remain replaceable implementation choices.
## Out of Scope
Agent Foundry is not:

- a hosted platform
- a general-purpose workflow engine
- only a model provider abstraction
- a replacement for every agent framework
- a promise of backend portability before adapters exist

## Design Promises
  
  - Process declarations stay framework-neutral
  - Typed I/O boundaries are non-negotiable
  - Provider/runtime-specific details live in adapters
  - Escape hatches are allowed, but marked non-portable
  - Adapter compatibility is validated with shared contract tests as adapters are added