from __future__ import annotations

import spot
import buddy
import copy
import heapq

from .types import ToolCall, VerifierDecision
from dataclasses import dataclass

class SpotVerifier:
    def __init__(self, tool_names: list[str], formula: str):
        self.tool_names = tool_names
        self.backend = SpotBackend(formula)
        self.current_set = self.backend.get_starting_set()

    def verify_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> VerifierDecision:
        back_res = self.backend.do_transition(
            self.current_set, set(call.name for call in calls)
        )
        if back_res.safety_error is None:
            self.current_set = back_res.next_set
            return VerifierDecision(allowed=True)
        safety_err = back_res.safety_error
        message = (
            f'The tools you have used in the batch {batch_id} violates the safety '
            f'condition. Try again. Your next response must satisfy the boolean '
            f'condition "{safety_err.condition_text}".'
        )
        if safety_err.satisfiable_examples:
            example = safety_err.satisfiable_examples[0]
            if len(example) == 0:
                message += (
                    f' One such example is to use no tools.'
                )
            elif len(example) == 1:
                message += (
                    f' One such example is to only use the tool {example[0]}.'
                )
            else:
                message += (
                    f' One such example is to use the tools '
                    f'{' and '.join(example)}.'
                )
        return VerifierDecision(allowed=False, message=message)

    def verify_halt(self) -> VerifierDecision:
        back_res = self.backend.do_halt(self.current_set)
        if back_res.liveness_error is None:
            return VerifierDecision(allowed=True)
        liveness_err = back_res.liveness_error
        if not liveness_err.can_halt:
            message = (
                f"You can never halt. Please continue your procedure."
            )
        else:
            message = (
                f"You are not allowed to halt at this state."
            )
            if liveness_err.halt_examples:
                example = liveness_err.halt_examples[0]
                steps = []
                for tools in example:
                    if len(tools) == 0:
                        steps.append("use no tools")
                    elif len(tools) == 1:
                        steps.append(f"only use the tool {tools[0]}")
                    else:
                        steps.append(f"use the tools {' and '.join(tools)}")
                message += (
                    " One sequence of tool batches that allows you to halt is: "
                    f"{'; then '.join(steps)}."
                )
        return VerifierDecision(allowed=False, message=message)


class SpotBackend:
    @dataclass
    class SafetyError:
        # Boolean condition of what needs to be satisifed, in human-readable text
        condition_text: str

        # Examples of satisfiable tool calls
        satisfiable_examples: list[list[str]]

    @dataclass
    class LivenessError:
        # True if the model has a path to halt. Otherwise the LTL condition forces the model to loop
        # forever.
        can_halt: bool

        # If halting is possible, this contains a list of paths that would reach a valid halting state
        halt_examples: list[list[list[str]]] | None = None

    @dataclass
    class TransitionResult:
        next_set: set[int]
        safety_error: SpotBackend.SafetyError | None = None

    @dataclass
    class HaltResult:
        liveness_error: SpotBackend.LivenessError | None = None

    @dataclass
    class Edge:
        """
        Used to better represent edge information from spot graphs.
        Need to store acceptance information if needed.
        """

        parent: 'SpotBackend'
        src: int
        dst: int
        cond: buddy.bdd

        def __str__(self):
            return (
                f'<Edge ({self.src})=>({self.dst})'
                f' :: {self.parent.write_bdd(self.cond)}>'
            )

        def __repr__(self):
            return self.__str__()

    def __init__(self, formulatxt):
        self.formula = spot.formula(formulatxt)

        self.automata = spot.translate(self.formula, 'GeneralizedBuchi', 'High')
        # self.user_write_automata_info(self.automata)

        self.scc_info = spot.scc_info(self.automata)
        # self.user_write_scc(self.scc_info)

        self.bdd_dict = self.automata.get_dict()
        self.halting_states = self.get_halting_states()

    def get_starting_set(self) -> set[int]:
        return {self.automata.get_init_state_number()}

    def do_transition(self, current_set: set[int], transition_set: set[str]) -> TransitionResult:
        transet = self.make_transet(transition_set)
        next_set = self.advance(current_set, transet)
        if not next_set:
            valid_bdd = self.valid_transition_bdd(current_set)
            min_sat = self.bdd_minimal_sat(valid_bdd)
            return self.TransitionResult(
                safety_error=self.SafetyError(
                    condition_text=self.write_bdd(valid_bdd),
                    satisfiable_examples=[min_sat]
                ),
                next_set=current_set
            )
        return self.TransitionResult(next_set=next_set)

    def do_halt(self, current_set: set[int]) -> HaltResult:
        if not self.halting_states:
            return self.HaltResult(
                liveness_error=self.LivenessError(
                    can_halt=False
                )
            )
        for state in current_set:
            if state in self.halting_states:
                return self.HaltResult()
        path = self.write_one_halting_path(current_set)
        if path == 'no-path':
            return self.HaltResult(
                liveness_error=self.LivenessError(
                    can_halt=False
                )
            )
        return self.HaltResult(
            liveness_error=self.LivenessError(
                can_halt=True,
                halt_examples=[path]
            )
        )

    def get_edges(self, u):
        """
        Given a node number, return list of `Edge`s going out of that node.
        """
        aut = self.automata
        edges = []
        for e in aut.out(u):
            edges.append(self.Edge(parent=self, src=e.src, dst=e.dst, cond=e.cond))
        return edges

    def bdd_traverse(self, bdd):
        """
        Example of traversing the BDD structure.
        Can be used to generate textual representation or DP techniques.
        """
        aut = self.automata

        bdd_dict = aut.get_dict()
        var_names = {
            bdd_dict.varnum(ap): ap.to_str()
            for ap in aut.ap()
        }

        def visit(node):
            if node == buddy.bddfalse:
                return 'false'
            if node == buddy.bddtrue:
                return 'true'
            var = buddy.bdd_var(node)
            low = buddy.bdd_low(node)
            high = buddy.bdd_high(node)
            name = var_names.get(var)
            return f'if({name}, {visit(high)}, {visit(low)})'

        return visit(bdd)

    def bdd_minimal_sat(self, bdd):
        """
        Using BDD traverse to find the minimal satisfiable assignment (
        minimum number of true variables).
        Can be used on accepted path generation.
        """
        aut = self.automata

        bdd_dict = self.bdd_dict
        var_names = {
            bdd_dict.varnum(ap): ap.to_str()
            for ap in aut.ap()
        }

        dp = {
            buddy.bddfalse.id(): (float('inf'), []),
            buddy.bddtrue.id(): (0, [])
        }

        def visit(node):
            if node.id() in dp:
                return dp[node.id()]
            lowcost, lowset = visit(buddy.bdd_low(node))
            highcost, highset = visit(buddy.bdd_high(node))

            cost, nodeset = lowcost, lowset
            if highcost != float('inf') and highcost + 1 < cost:
                cost, nodeset = highcost + 1, highset + [buddy.bdd_var(node)]

            dp[node.id()] = cost, nodeset
            return (cost, nodeset)

        cost, varset = visit(bdd)
        if cost == float('inf'):
            return None
        return list(map(var_names.get, varset))

    @staticmethod
    def user_write_automata_info(aut):
        """
        Write information about the automata.
        Used to double check with the spot's online visualizer.
        """
        print('-' * 24)
        print('Number of states:', aut.num_states(), sep='\t')
        print('Number of edges:', aut.num_edges(), sep='\t')
        print('Number of acceptence sets:', aut.num_sets(), sep='\t')

    @staticmethod
    def user_write_scc(scc):
        """
        Write information about the SCCs within automata.
        Used to double check with the spot's online visualizer.
        """
        print('-' * 24)
        print('Number of SCCs:', scc.scc_count(), sep='\t')
        print('Accepting SCCs:', end='\t')
        for i in range(scc.scc_count()):
            if scc.is_accepting_scc(i):
                print(i, end=' ')
        print()

    def write_bdd(self, bdd):
        """
        Write BDD as a nice formula text.
        """
        return spot.bdd_format_formula(self.bdd_dict, bdd)

    def make_transet(self, str_transet):
        """
        Turn transition set that has string elements into an integer set
        used internally.
        """
        return set(map(self.bdd_dict.varnum, str_transet))

    def make_transet_bdd(self, transet):
        """
        Turn internal transition set into equivalent BDD.
        Can be used to check edge conditions.
        """
        bdd = buddy.bddtrue
        d = self.bdd_dict
        for ap_obj in self.automata.ap():
            var_id = d.varnum(ap_obj.to_str())
            var_bdd = buddy.bdd_ithvar(var_id)
            if var_id in transet:
                bdd &= var_bdd
            else:
                bdd &= buddy.bdd_not(var_bdd)
        return bdd

    def bdd_eval(self, bdd, transet):
        def visit(node):
            if node == buddy.bddtrue:
                return True
            if node == buddy.bddfalse:
                return False

            var_id = buddy.bdd_var(node)
            if var_id in transet:
                return visit(buddy.bdd_high(node))
            return visit(buddy.bdd_low(node))

        return visit(bdd)

    def advance(self, curset, transet):
        """
        Advance the current set of states based on the given transition set.
        Returns the next set of states, possibly empty.
        """
        # e.g. curset = {0, 1}, transet = {dict.varnum('open'), dict.varnum('close')}
        log = lambda *args: ()
        # log = print

        log('curset', curset)
        nxtset = set()
        # log('transet bdd is', write_bdd(bdd))
        for u in curset:
            log('edges from', u)
            for e in self.automata.out(u):
                log(' to', e.dst, 'on', self.write_bdd(e.cond))
                if e.dst not in nxtset and self.bdd_eval(e.cond, transet):
                    log('  matched!')
                    nxtset.add(e.dst)
        return nxtset

    def valid_transition_bdd(self, curset):
        """
        Find BDD equivalent to a safe transition from current set of states.
        """
        bdd = buddy.bddfalse
        for u in curset:
            for e in self.automata.out(u):
                bdd |= e.cond
        return bdd

    def empty_omega_word(self):
        """
        Returns the word `\\emptyset^\\omega`.
        Can be used to find halting states
        """
        aut = self.automata
        bdd_dict = self.bdd_dict

        empty_letter = buddy.bddtrue
        for ap in aut.ap():
            empty_letter &= buddy.bdd_nithvar(bdd_dict.varnum(ap))

        word = spot.twa_word(bdd_dict)
        word.cycle.append(empty_letter)
        return word

    def is_halting_state(self, state, word=None):
        """
        Check if the state is a halting state of the automata.
        Equivalently, is it acceptable to halt on this state.
        """
        aut = self.automata
        if word is None:
            word = self.empty_omega_word()

        rooted = copy.copy(aut)
        rooted.set_init_state(state)
        return word.intersects(rooted)

    def get_halting_states(self, word=None):
        """
        Returns the set of halting state numbers of the automaton.
        """
        aut = self.automata
        if word is None:
            word = self.empty_omega_word()

        halting = []
        for state in range(aut.num_states()):
            if self.is_halting_state(state, word):
                halting.append(state)
        return set(halting)

    def get_one_halting_path(self, states, halting_states=None):
        aut = self.automata
        if halting_states is None:
            halting_states = self.get_halting_states()

        queue = []
        marked = set()
        for state in states:
            heapq.heappush(queue, (0, 0, state, []))

        final_path = None
        while queue:
            (ulencost, utoolcost, u, upath) = heapq.heappop(queue)

            if u in marked:
                continue
            marked.add(u)

            if u in halting_states:
                final_path = upath
                break

            for e in self.get_edges(u):
                v = e.dst
                if v in marked:
                    continue

                vtoolcost = utoolcost + len(self.bdd_minimal_sat(e.cond))

                vpath = upath.copy()
                vpath.append(e.cond)

                heapq.heappush(queue, (ulencost + 1, vtoolcost, v, vpath))

        if final_path is None:
            return None
        return final_path

    def write_one_halting_path(self, states, halting_states=None):
        aut = self.automata
        path = self.get_one_halting_path(states, halting_states)
        if path is None:
            return 'no-path'
        example = []
        for bdd in path:
            example.append(self.bdd_minimal_sat(bdd))
        return example

    def advance_loop(self):
        """
        CLI interface to simulate transitions on the automata.
        """
        curset = {self.automata.get_init_state_number()}
        halting_states = self.get_halting_states()
        while True:
            print('> Current Set:', curset)

            do_halt = False
            while True:
                transtxt = input("""
    Enter transition set, space seperated APs
    Enter HALT to finish transitions
    Enter EXIT to abort the process
    >>> """).strip()
                if transtxt == "EXIT":
                    return
                if transtxt == "HALT":
                    do_halt = True
                    break
                aps = transtxt.split()

                try:
                    transet = self.make_transet(aps)
                    break
                except:
                    print('Try again')

            if do_halt:
                for state in curset:
                    if state in halting_states:
                        print('OK to halt')
                        return
                print('Liveness condition violated!')
                path = self.write_one_halting_path(curset)
                if path == 'no-path':
                    print('You are not allowed to halt in your current state')
                else:
                    print('You can halt. One such example is', path)
                continue

            nxtset = self.advance(curset, transet)
            if not nxtset:
                print('Safety condition violated!')
                valid_bdd = self.valid_transition_bdd(curset)
                print('Your next action must satisfy', self.write_bdd(valid_bdd))
                continue

            curset = nxtset
