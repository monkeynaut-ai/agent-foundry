## Guidance You Provided

### Pre-Design Corrections

1. **LSP tool usage** — You noticed I hadn't used the pyright LSP server during the bug-fix phase and asked how to ensure I use it in future sessions. This led to adding the LSP preference to your global CLAUDE.md.

### During Design Options

2. **Ubuntu "more compatible" claim** — I suggested Ubuntu was "more compatible" as a base image option. You challenged this ("why is ubuntu option more compatible?") and I had to concede it wasn't — python:3.13-slim is Debian bookworm and equally compatible.

3. **Missing option in API key question** — After I explained how the handler's env forwarding mechanism works, I failed to list it as one of the selectable options. You caught this: "after answering my question about the handler, you did not list an option that uses the handler."

4. **CC invocation is in scope** — I suggested deferring the `claude -p` vs `claude-code --yes` decision to a later phase. You pushed back: "if 'claude -p' or 'claude-code --yes' is run in the container, and we are defining the Dockerfile, why do you suggest punting this decision?" I agreed it belonged in scope.

5. **settings.json for tool permissions** — I was heading toward CLI flags for allowed tools. You suggested: "can't the allowed tools be defined in settings.json?" — a much cleaner declarative approach that I adopted.

6. **PTY protocol for version notification** — I proposed writing a marker file for version staleness. You redirected me to the existing interrupt protocol: "I do not want to use a marker file. I want the agent foundry to be notified of this. Aren't we establishing a protocol based on pty for the agent/container to ask questions?" This became the `ARCHIPELAGO_UPDATE_AVAILABLE` marker.
	1. There's more to this. CC did ask how we wanted to keep CC updated to the latest version in the docker container. This was an excellent point (really excellent). During the course of our conversation about options
	2. Originally CC provided 2 options for installing CC into the image, and using "curl ... | bash" was not one of the options, even though this is Anthropic's recommendation. When I asked if there are other options, CC found the curl option and stated this is Anthropic's recommendation.

### Pattern

Your guidance consistently pulled the design toward **consistency with existing patterns** (PTY protocol, settings.json) and **challenged assumptions** I made without evidence (Ubuntu compatibility, scope deferral). You also caught presentation errors where I failed to follow through on my own explanations.

## How to Avoid These in the Future

1. **Unsupported claims** (Ubuntu "more compatible") — I stated something as fact without evidence. Fix: I should flag when I'm uncertain rather than presenting assumptions as conclusions.

2. **Dropping options after explaining them** (handler env forwarding) — I did the analysis work but didn't carry it through to the presentation. Fix: This is just a consistency/attention error. Hard to prevent systematically.

3. **Defaulting to "punt it"** (CC invocation scope) — I reflexively narrowed scope without considering whether the decision was inherently coupled to the current work. Fix: Before suggesting deferral, I should ask "does this decision belong to whoever owns the artifact we're designing?"

4. **Inventing new mechanisms instead of using existing ones** (marker file vs PTY protocol, CLI flags vs settings.json) — This is the most significant pattern. I proposed novel solutions when the codebase already had established patterns that applied directly.

That last one is the root cause of items 4, 5, and 6. The fix is: **before proposing any mechanism, I should search the codebase for existing patterns that solve the same category of problem.** I should treat "is there already a way to do this?" as a mandatory step, not an afterthought.
