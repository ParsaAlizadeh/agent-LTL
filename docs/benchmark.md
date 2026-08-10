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
| [AppWorld](https://arxiv.org/abs/2407.18901) | 750 tasks over 9 realistic apps and 457 APIs, with state-based success and collateral-damage checks; already has an explicit `complete_task` API | A possible later scalability benchmark through a deliberately coarsened tool-name wrapper |
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
| Resource lifecycle | `G(!(lock & unlock)) & G(lock -> X(!lock U unlock))` | Repeated acquire/release behavior |
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

## Scope decisions and remaining questions

Several apparent limitations are deliberate consequences of the project's
simple propositional-LTL abstraction. They should be stated as assumptions and
reflected in benchmark selection, rather than treated as implementation defects.

### Accepted scope decisions

#### The benchmark uses tool names as atomic propositions

For this benchmark profile, each scenario deliberately reduces calls to
`set(call.name for call in calls)` before invoking `SpotVerifier`. Arguments and
object identities are outside this benchmark's policy alphabet. The runtime
also permits scenarios to rename tools or add environment-state symbols, but
the restricted profile keeps specifications easier to understand and compare.

The benchmark guarantee is intentionally about tool-name traces. It cannot
express “close the same file that was opened” or “refund this particular
order.” Benchmark scenarios should therefore use policies whose truth depends
only on tool names, possibly exposing semantically distinct wrapper tools when
needed. Parameterized or quantified monitoring is a possible extension, not a
requirement for the present project.

#### A response batch is one simultaneous set

Order and multiplicity inside a response are deliberately absent. A letter such
as `{authorize, transfer}` says that both propositions hold at the same logical
time; neither call is temporally before the other. This preserves the agent's
freedom to propose independent actions together.

If two tools must not occur simultaneously, a formula such as
`G(!open | !close)`, equivalently `G(!(open & close))`, forbids their
co-occurrence. That formula alone does not impose an order. Ordering must be
specified across batches. For example,
`G(!(open & close)) & G(open -> X(!open U close))` requires `open` and `close`
to occur separately and requires a later `close` before another `open`.
Policies and benchmark descriptions should use these simultaneous-batch
semantics consistently.

#### Accepted tool calls are assumed to succeed

The occurrence of an accepted tool name is treated as the occurrence of the
corresponding action. Tool failures, partial effects, retries, and rollback are
outside the present model. Under the assumption that failures can be avoided,
advancing the automaton when a batch is accepted is consistent with the
project's semantics.

Benchmarks should use deterministic, reliable tool implementations and should
not inject execution failures. A later failure-aware version could introduce
`proposed`, `succeeded`, or `failed` events, but that additional real-world
complexity is not needed to evaluate the current theoretical idea.

#### Completion witnesses are policy-valid by construction

The suggested completion sequence follows automaton transitions from the
current active-state set to a state that accepts the scenario's terminal
valuation forever. Each suggested batch is
a satisfying valuation of its chosen transition. The full witness therefore
respects the LTL formula, including its safety constraints, rather than merely
pointing toward a liveness goal.

Under the current abstraction—where the policy depends only on tool names and
accepted tools are assumed available and successful—this is the relevant notion
of validity. Environment preconditions and execution failures would create a
separate realizability problem, but those features are outside the current
scope.

### Remaining questions

#### Completion and waiting are explicit control actions

The scenario-controlled interaction protocol distinguishes user messages,
autonomous continuation, verified halt requests, and unverified aborts. A
tool-free response is not itself a termination request. After accepted tools,
the scenario can continue immediately so the model observes their outputs, ask
for user input, or explicitly request verification of the terminal valuation.

These out-of-band actions include:

- `continue`, meaning that tool results should be returned to the agent for
  another model turn;
- `request_halt`, meaning that the agent believes the procedure is complete and
  the verifier should check the scenario's terminal valuation forever.

Timeouts, interruptions, explicit aborts, and maximum-turn exhaustion must not
be counted as verified completion.

#### Persistent inactivity remains outside enforceable liveness

An agent that never requests termination can remain inactive or postpone an
eventual obligation forever without producing a finite liveness violation. This
is not an implementation defect that the project can remove; it is the reason
general liveness cannot be checked like safety from finite prefixes.

The benchmark should nevertheless distinguish policy conformance from utility.
A task-success oracle prevents a safe but useless no-op run from receiving full
credit, while max-turn exhaustion or failure to request halt should be reported
as nontermination. A formula such as `F goal` can reject an attempted premature
halt, but it cannot force a forever-running agent to attempt `goal`.

#### The termination semantics needs a formal comparison

The evaluation should include `∅^ω`, scenario-defined terminal valuations,
LTLf, and an explicit end-marker semantics.
It should show where they agree, where they differ, and why permanent tool
inactivity is appropriate for the intended agents. This remains both a
theoretical question and an important part of positioning the contribution.

## A practical experimental sequence

1. Build 30–50 deterministic formula scenarios and validate the monitor against
   exhaustive traces.
2. Define and implement a protocol that distinguishes continuing after tool
   execution, waiting for user input, and requesting verified termination.
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
