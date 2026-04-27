# DSPy Evaluation

> Evaluation of DSPy as an optimization layer for Archipelago agent components.

DSPy is relevant to Archipelago primarily as an **inner-loop optimization layer** for agent components, not as a replacement for your **workflow orchestrator**.

## What DSPy is (in the terms that matter for Archipelago)

- DSPy is a Python framework for building **modular LM programs** and "compiling" them into effective prompts/parameters via **optimizers** driven by a metric. ([DSPy](https://dspy.ai/?utm_source=chatgpt.com "DSPy"))

- It formalizes modules with **Signatures**: declarative input/output specs for an LM call. ([DSPy](https://dspy.ai/learn/programming/signatures/?utm_source=chatgpt.com "Signatures"))


This maps cleanly onto your "typed capability" approach: signatures resemble capability I/O schemas, and optimizers resemble your "auto-tune" idea.

## Some Thoughts about DSPy
### How DSPy fits into the Archipelago workflow

#### 1) Use DSPy to improve _specific_ Archipelago agents/components with measurable metrics

Best targets are components where you can define a stable metric and have lots of examples:

- **Spec Linter / Consistency Checker**: classify issues, propose fixes; metric from labeled spec defects or human accept/reject. (DSPy signatures + optimizers fit well.) ([DSPy](https://dspy.ai/learn/programming/signatures/?utm_source=chatgpt.com "Signatures"))

- **PR Reviewer Agent**: detect missing tests/edge cases/security items; metric from downstream bug rate, review acceptance, or a rubric. ([DSPy](https://dspy.ai/?utm_source=chatgpt.com "DSPy"))

- **Planner sub-tasks** (not the whole orchestrator): e.g., "convert FeatureSpec → PR/commit plan quality score" with a rubric. ([DSPy](https://dspy.ai/learn/optimization/optimizers/?utm_source=chatgpt.com "Optimizers"))

- **Retrieval/RAG submodules** (if you do retrieval over artifacts): DSPy has explicit patterns and tutorials for RAG-style pipelines. ([DSPy](https://dspy.ai/tutorials/rag/?utm_source=chatgpt.com "Tutorial: Retrieval-Augmented Generation (RAG) - DSPy"))


#### 2) DSPy + your eval harness = "Auto-tune Archipelago" implemented for real

Your earlier plan included a prompt/workflow optimizer. DSPy provides the mechanism: given (program, metric, examples), an optimizer tunes prompts/parameters to maximize the metric. ([DSPy](https://dspy.ai/learn/optimization/optimizers/?utm_source=chatgpt.com "Optimizers"))
So: **Archipelago Evals** produces scored tasks → DSPy optimizers tune a module → you gate rollout based on eval regression.

#### 3) DSPy is not your orchestrator

DSPy doesn't give you the control-plane features you need:

- DAG execution across heterogeneous agents/tools

- Docker session lifecycle + breakpoints + live pause/resume for Claude Code

- artifact store, checkpoint/resume, permissions gating


So the right integration is: **Orchestrator owns workflow + state; DSPy owns optimization inside individual LM modules.** ([DSPy](https://dspy.ai/?utm_source=chatgpt.com "DSPy"))

### How to integrate DSPy into "Control Plane Lite"

Treat a DSPy program as just another **capability**:

- `capability_id: spec.lint_dspy` or `review.pr_review_dspy`

- Inputs/outputs defined by your canonical schemas; inside the capability you map them to DSPy Signatures. ([DSPy](https://dspy.ai/learn/programming/signatures/?utm_source=chatgpt.com "Signatures"))

- Run an offline "compile/optimize" job (DSPy optimizer) as a separate orchestration workflow step, producing a versioned artifact (prompt/weights) that your runtime capability loads. ([DSPy](https://dspy.ai/learn/optimization/optimizers/?utm_source=chatgpt.com "Optimizers"))


### Where DSPy is _not_ a good fit (initially)

- Your **Claude Code "implement this feature spec" worker**: CC already has a strong closed-loop with real tests (the best metric). DSPy adds little unless you're trying to optimize CC's instruction protocol or checkpoint emission format.

- Full end-to-end agentic workflow optimization: DSPy can optimize modules, but end-to-end orchestration changes are better handled by your eval harness + orchestrator-level A/B.


### Recommended first DSPy use inside Archipelago

Start with one narrow, high-signal module:

- **Spec Linter** (signature = FeatureSpec → Issues+Fixes; metric = human label/rubric + downstream defect rate proxy), then use a DSPy optimizer to tune it. ([DSPy](https://dspy.ai/learn/programming/signatures/?utm_source=chatgpt.com "Signatures"))


If you share which Archipelago component currently has the most variance (spec quality, review quality, planning quality, retrieval quality), I can map it to a DSPy Signature + metric + dataset plan that matches your orchestrator artifacts.
