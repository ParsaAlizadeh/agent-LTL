# Benchmarking Liveness-Aware Runtime Enforcement

The strongest benchmark direction is a termination-aware extension of
τ-bench/τ³-bench, backed by a small controlled LTL suite. That gives the project
realistic workflows, deterministic task-success checks, a direct comparison
with safety-focused runtime enforcers, and scenarios where premature
termination is visibly harmful.

## How to position the contribution

Traditional runtime verification cannot generally refute liveness from a
finite prefix: an event required “eventually” may still occur later. This
limitation is central to Büchi-monitor theory. [A Note on Monitors and Büchi
Automata](https://arxiv.org/abs/1507.01020) discusses this explicitly.

This project changes the question at termination. For an accepted finite trace
`w`, it decides:

```text
L_halt(φ) = {w | w · ∅^ω ⊨ φ}.
```

Once the agent asks to halt, the future is no longer unknown: it has been fixed
to permanent tool inactivity. That makes pending eventual obligations
decidable, and the LLM can be reprompted to produce a satisfying continuation.

The contribution should therefore be described as:

> Runtime enforcement of safety during execution, combined with
> liveness-aware completion control and automaton-guided repair at termination.

It should not be presented as general “runtime enforcement of liveness.” An
agent that runs forever can still postpone `F p` forever without producing a
finite bad prefix. The mechanism guarantees that it cannot terminate normally
while leaving such an obligation unresolved.

There is also important prior theory to acknowledge. LTL over finite traces,
and the practice of extending a finite trace with a repeating terminal state,
are established topics. In fact, repeatedly appending an end state with all
ordinary propositions false is not equivalent to ordinary LTLf for every
formula. [De Giacomo, De Masellis, and
Montali](https://ojs.aaai.org/index.php/AAAI/article/view/8872) characterize this
distinction. The `∅^ω` semantics should therefore be presented as a deliberate
termination semantics and compared experimentally with LTLf or an explicit
`finish` event.

## Closest literature

The closest systems still leave a useful gap:

- [Agent-C](https://arxiv.org/abs/2512.23738) is the most important
  comparison. It enforces formal temporal safety constraints during tool-call
  generation and evaluates on τ-bench retail and airline tasks. Its reported
  emphasis is 100% safety conformance, not Büchi liveness or rejecting
  premature termination with an accepting-suffix witness.

- [AgentSpec](https://arxiv.org/abs/2503.18666) provides customizable runtime
  rules using triggers, predicates, and enforcement actions across code
  execution, embodied agents, and autonomous driving. Its evaluation is
  primarily about preventing unsafe actions.

- [Formal-LLM](https://arxiv.org/abs/2402.00798) supervises LLM plan generation
  using an automaton. It is closer to constrained planning than to gating
  real-world tool effects one response at a time.

- [LogicGuard](https://arxiv.org/abs/2507.03293) uses LTL-producing critics to
  improve embodied agents on BEHAVIOR and Minecraft, but analyzes trajectories
  and learns constraints rather than providing a deterministic pre-execution
  gate with termination semantics.

- [Pro2Guard](https://arxiv.org/abs/2508.00500) predicts future unsafe states
  using probabilistic model checking. It provides proactive safety estimates
  rather than hard, general LTL completion checks.

No established benchmark was found that specifically measures the combination
of:

1. pre-execution rejection of bad prefixes;
2. rejection of premature completion under `∅^ω`;
3. automaton-generated shortest completion guidance; and
4. successful recovery by reprompting the same LLM.

That combination is the empirical gap worth targeting.

## Candidate benchmarks

| Benchmark | Why it fits | Recommended use |
| --- | --- | --- |
| [τ-bench / τ³-bench](https://github.com/sierra-research/tau2-bench) | Stateful retail, airline, telecom, and banking workflows; policies, simulated users, database-state evaluation, and repeated-run reliability. The original paper introduced `pass^k`. [Paper](https://arxiv.org/abs/2406.12045) | Best flagship benchmark and direct Agent-C comparison |
| [STATE-Bench](https://github.com/microsoft/STATE-Bench) | 450 procedural enterprise tasks across travel, customer support, and shopping, with sandbox databases and final-state assertions | Strong second-domain generalization benchmark |
| [AppWorld](https://arxiv.org/abs/2407.18901) | 750 tasks over 9 realistic apps and 457 APIs, with state-based success and collateral-damage checks; already has an explicit `complete_task` API | Excellent after supporting arguments, outcomes, and larger tool alphabets |
| [ToolSandbox](https://machinelearning.apple.com/research/toolsandbox-stateful-conversational-llm-benchmark) | Stateful tool execution, intermediate milestone DAGs, user simulation, and tasks involving implicit dependencies | Easiest environment for early integration experiments |
| [AgentDojo](https://arxiv.org/abs/2406.13352) | 97 realistic tasks and 629 prompt-injection security cases across email, banking, and travel | Adversarial robustness track |
| [BEHAVIOR-1K](https://arxiv.org/abs/2403.09227) | Human-grounded household activities with intuitive cleanup obligations such as turning appliances off and returning objects | Compelling embodied demonstration, but expensive to integrate |

ToolEmu and Agent-SafetyBench are useful for mining risks and scenario ideas,
but they should not be the main conclusion benchmark. ToolEmu relies partly on
LM-emulated tools and judging, while Agent-SafetyBench is broad but mainly
oriented toward identifying safety failures.
[ToolEmu](https://arxiv.org/abs/2309.15817),
[Agent-SafetyBench](https://arxiv.org/abs/2412.14470).

## Recommended benchmark structure

### 1. Controlled temporal-property track

This establishes correctness and isolates the behavior of the enforcer
independently of environment complexity.

| Category | Example | What it tests |
| --- | --- | --- |
| Immediate safety | `G(!(open & close))` | Rejection before any tool executes |
| Precedence | `(!access_private) W authenticate` | Historical ordering constraints |
| Required goal | `F issue_refund` | Rejection of doing nothing and halting |
| Response/cleanup | `G(begin_return -> F close_case)` | Pending obligations at termination |
| Commit or compensate | `G(deploy -> F(commit \| rollback))` | Multiple valid recovery paths |
| Resource lifecycle | `G(lock -> X(!lock U unlock))` | Repeated acquire/release behavior |
| Mixed policy | Safety conjunction plus response obligations | Interaction between the two checks |
| Non-terminating policy | `GF heartbeat` | Correctly recognizing that no finite halt is legal |

The suite should include satisfiable, unsatisfiable, haltable, temporarily
non-haltable, and permanently non-haltable formulas. Short traces should be
generated exhaustively so that online decisions can be compared against an
offline oracle.

### 2. Enterprise lifecycle track

A fixed τ-bench version should be forked and formal policies attached to its
tool workflows. Suitable scenarios include:

- Return initiated → refund or exchange completed → return instructions issued
  → case closed.

- Reservation modification started → charge settled or rolled back → updated
  itinerary issued.

- Payment captured → order created or payment reversed.

- Support escalation started → handoff recorded.

- Account recovery started → identity verified → credentials reset or recovery
  cancelled.

- Database transaction begun → commit or rollback.

- Deployment lock acquired → deploy → health check → commit or rollback →
  release lock.

The important pattern is not merely “B must occur after A.” It is:

> Once A has happened, the agent must not quietly stop until some acceptable
> completion or compensation action has occurred.

This is where a safety-only monitor and the termination-aware monitor should
diverge.

### 3. Adversarial track

AgentDojo tasks can be reused, or adversarial tool outputs can be injected into
the enterprise track:

- A malicious email asks the agent to ignore a pending cleanup.

- A user insists that the agent stop after an incomplete refund.

- A tool result falsely claims the task is complete.

- The agent is instructed to repeat rejected batches.

- A prompt injection attempts to bypass authentication or termination checks.

A deterministic monitor should remain conformant even when the model is
compromised. The interesting measurement is whether it can also guide that
compromised or confused model back to a valid completion.

## The headline measurements

A suitable primary metric is:

> Completion Under Temporal Policy = task goal satisfied ∧ no executed
> bad-prefix violation ∧ termination accepted.

Its components should also be reported separately so a system cannot score well
by merely refusing everything or never terminating.

Other important metrics are:

- Safety conformance: percentage of executed traces without a bad prefix.

- Valid termination rate: percentage of episodes ending with
  `w · ∅^ω ⊨ φ`.

- Premature-halt detection recall.

- Liveness repair rate: fraction of rejected, recoverable halt attempts that
  eventually reach an accepted halt.

- Completion stretch: extra responses used versus the shortest automaton
  witness.

- Rejection count and repeated-rejection rate.

- Nontermination/max-turn rate.

- Task success and collateral damage from the environment’s deterministic
  evaluator.

- Added tokens, latency, and monetary cost.

- `pass^k` across repeated runs, following τ-bench.

- Performance by formula family, automaton size, number of tools, and
  obligation depth.

The critical ablation is:

1. Unrestricted agent.
2. Policy only in the system prompt.
3. Safety gate, but halt always allowed.
4. Safety plus halt gate with generic “continue” feedback.
5. Safety plus halt gate with the shortest witness.
6. Explicit `finish` action enforced as an ordinary safety precondition.
7. Agent-C on the common safety subset.

A comparison between 3, 4, and 5 isolates the actual liveness contribution.
Comparison 6 addresses the likely reviewer question: “Could this just be
encoded as a safety rule around `finish`?”

## Major issues to address before a credible evaluation

These issues are more consequential than adding more scenarios.

### 1. Tool arguments and identities are currently lost

Calls are reduced to `set(call.name for call in calls)` in
[`spot_verifier.py`](../agentltl/spot_verifier.py). Real policies require
“close the same file,” “refund the same order,” and “release the same lock.” The
project will eventually need parameterized events, grounded propositions, or
quantified/parametric monitoring.

### 2. Order and multiplicity inside a batch are lost

`{authorize, transfer}` has no internal order, and two transfers become one
proposition. The project should either formally declare batches simultaneous
and atomic, enforce one call per response, or linearize calls before
verification.

### 3. A proposed call currently satisfies the formula even if execution fails

The verifier advances before execution in
[`spot_verifier.py`](../agentltl/spot_verifier.py), while tool execution occurs
later in [`agent_loop.py`](../agentltl/agent_loop.py). Real monitoring needs
events such as `proposed`, `started`, `succeeded`, and `failed`, or a
transactional rollback scheme. Otherwise a failed `close` can discharge an
obligation.

### 4. Automaton reachability is not environment realizability

The shortest witness may suggest a tool whose preconditions are false. For
benchmark-quality feedback, paths should be calculated in the product of the
policy automaton and the environment state—or suggested calls should at least
be validated against tool preconditions.

### 5. Every exit path must pass through halt verification

The current loop can finish because of a turn limit, interruption, or blank user
input. A benchmark needs an explicit agent `finish` signal, and timeouts or
max-turn exhaustion must be scored as nontermination rather than successful
completion.

### 6. Safety-only tasks permit trivial inactivity

Temporal conformance should be paired with a task-success oracle or `F goal`;
otherwise an agent that does nothing may be perfectly safe.

### 7. The termination semantics needs a formal comparison

The evaluation should include `∅^ω`, LTLf, and explicit-`done` semantics. It
should show where they agree, where they differ, and why permanent tool
inactivity is appropriate for the intended agents.

## A practical experimental sequence

1. Build 30–50 deterministic formula scenarios and validate the monitor against
   exhaustive traces.
2. Implement explicit termination and post-execution success events.
3. Port the exact τ-bench subset used by Agent-C for a controlled comparison.
4. Add liveness annotations to lifecycle operations and run at least five
   trials per task and model.
5. Add STATE-Bench or AppWorld as a generalization domain.
6. Add AgentDojo-style prompt injection only after the non-adversarial benchmark
   is stable.

If only one showcase example is developed, it should use a refund or deployment
workflow. Let the agent begin an irreversible operation and then confidently
announce completion too early. A safety-only system has nothing more to reject;
the termination-aware system rejects termination, supplies `issue_refund;
close_case` or `health_check; commit/rollback; release_lock`, and measures
whether the LLM successfully repairs the procedure. That single contrast
communicates the project’s utility especially well.
