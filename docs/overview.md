# Runtime Enforcement for Tool-Using Language Agents

Language-model agents can affect the world by calling tools: opening a file,
publishing a record, sending a message, or operating some external system. This
project places a runtime enforcer between such an agent and its tools. The agent
may propose actions freely, but a proposal is executed only when it remains
consistent with a policy written in Linear Temporal Logic (LTL).

The purpose of the enforcer is not to prove that the model reasons correctly.
It constrains the observable sequence of tool use. This makes temporal rules
such as “never perform these actions together,” “close before opening again,”
or “every open must eventually be followed by a close” enforceable at the point
where proposed language turns into real-world action.

## Tool use as a temporal trace

Let `T` be the finite set of tools available to the agent. Each model response
proposes a batch of zero or more tool calls. For verification, that batch is
represented by the subset of `T` whose tools occur in the response. The exact
arguments, order, and repeated calls to the same tool are not part of this
abstraction. For example, a response containing two calls to `open` and one to
`close` is represented by the single letter `{open, close}`.

A sequence of responses therefore induces a word over the alphabet `2^T`:

```text
{open}, {}, {close}, ...
```

Here `{}` denotes a step in which the agent uses no tools. LTL propositions are
the tool names, so a formula describes which infinite words of tool batches are
permitted. The formula is translated into a nondeterministic Büchi automaton,
and the enforcer tracks the set of automaton states still active after the
accepted prefix. A set is needed because the same observed prefix may be
consistent with several possible automaton runs.

## Rejecting unsafe proposals before they act

For every response, the enforcer tentatively advances all active states using
the proposed tool set. If no state remains active, the prefix has no run through
the policy automaton: the proposed batch has crossed a boundary from which the
policy cannot be satisfied. This empty active-state set is the runtime signal
for a safety violation.

The complete batch is then rejected before any of its calls execute. The world
and the enforcer both remain at their previous state, so a partially executed
batch cannot leak through the policy gate. The response is returned to the
agent as a failed proposal, together with:

- a Boolean condition describing the tool combinations that are legal for the
  next step; and
- an example satisfying batch, chosen to use as few tool names as possible.

The agent is asked to try again using that feedback. If at least one automaton
state remains active, the new state set is committed and the entire batch is
allowed to execute.

This mechanism deals with violations that have a finite, observable bad prefix.
It does not falsely declare an eventual obligation broken merely because it has
not yet been completed: on a finite trace, the agent may still fulfill it later.

## Interpreting termination

LTL normally describes infinite behavior, while an agent procedure is expected
to finish. The bridge between the two is to interpret halting as permanent
inactivity. If the accepted finite trace is `w`, terminating at that point means
checking the infinite word

```text
w . {}^omega
```

In other words, after halting the agent uses no tool forever. This is stronger
than observing one tool-free response: a response with no calls contributes one
`{}` step, whereas halting commits every future step to `{}`.

When the interaction has no new user input and requests termination, the
enforcer checks whether the infinite empty suffix is accepted from at least one
currently active automaton state. If it is, all temporal obligations are
compatible with stopping and the procedure may end. If it is not, halting would
fail the policy—most importantly when an eventual or other liveness obligation
remains—so the agent is prompted to continue.

When completion is reachable, the feedback includes an example sequence of
tool batches leading to a state from which halting is valid. The sequence is
chosen to minimize the number of additional responses and, among equally short
sequences, the number of tool names used. It is a concrete witness for a fast
way to discharge the remaining obligations, not a requirement that the agent
follow that exact route. If no such state is reachable, the policy admits no
valid termination from the current situation and the agent is told that it
must continue indefinitely.

For example, under `G(open -> F close)`, an accepted `open` creates an eventual
`close` obligation. Stopping immediately would extend the trace with no future
`close`, so termination is rejected and a batch containing `close` can be
suggested. Once `close` has occurred, permanent inactivity is compatible with
the formula and halting can be accepted.

## What the enforcer guarantees

The resulting interaction is a feedback-controlled loop: the language model
proposes, the temporal monitor decides, and only accepted proposals affect the
world. Safety-like failures are blocked at the first batch that eliminates all
legal automaton runs; liveness obligations are settled at the moment the finite
procedure attempts to become an infinite inactive suffix.

The guarantee is deliberately scoped to the chosen abstraction. It concerns
which tool names occur together and over time. It does not by itself constrain
tool arguments, natural-language output, tool results, or effects that bypass
the gated tool interface. Consequently, the intended guarantee relies on all
relevant real-world actions passing through the enforcer and on rejected calls
never being executed. Within that boundary, an unreliable or nondeterministic
agent can be given useful corrective feedback while the policy—not the model's
own judgment—remains the authority over action and termination.

As with runtime monitoring in general, an infinite execution that never asks to
halt cannot be forced to fulfill a liveness obligation merely by recognizing
finite bad prefixes: there may always appear to be time to make progress later.
The project instead guarantees that detected bad prefixes do not execute and
that a normally completed procedure is accepted only when its infinite inactive
continuation satisfies the policy. Reprompting and completion witnesses are the
mechanism for steering the agent toward that valid endpoint.
