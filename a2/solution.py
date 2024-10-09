from constants import *
from environment import *
from state import State
import numpy as np
from functools import lru_cache


class Solver:

    def __init__(self, environment: Environment):
        # Initialize the solver with the given environment, setting up
        # state values, policy, and relevant parameters such as epsilon
        # and gamma for convergence and discounting.
        self.environment = environment
        self.state_values = {}
        self.policy = {}
        self.epsilon = environment.epsilon
        self.gamma = environment.gamma
        self.policy_stable = False

    @staticmethod
    def testcases_to_attempt():
        return [1, 2, 3, 4, 5, 6]

    def get_transition_outcomes(self, state, action):
        """
        Return a list of (probability, next_state, reward) tuples representing each possible outcome of performing the
        given action from the given state.
        """
        outcomes = []

        # Check if the state is solved (terminal state)
        if self.environment.is_solved(state):
            return [(1.0, state, 0.0)]  # Stay in the same state with no reward

        # Handle normal transitions
        for prob, drift in [(1 - self.environment.drift_cw_probs[action] - self.environment.drift_ccw_probs[action], 0),
                            (self.environment.drift_cw_probs[action], SPIN_RIGHT),
                            (self.environment.drift_ccw_probs[action], SPIN_LEFT)]:
            for double_move in [False, True]:
                movements = [drift] if drift else []
                movements.append(action)
                if double_move:
                    movements.append(action)

                next_state = state
                total_reward = 0
                for move in movements:
                    reward, next_state = self.environment.apply_dynamics(next_state, move)
                    total_reward += reward
                    if next_state == state:  # Break if returned to the original state
                        break

                move_prob = prob * (self.environment.double_move_probs[action] if double_move else (
                        1 - self.environment.double_move_probs[action]))
                outcomes.append((move_prob, next_state, total_reward))

        return outcomes

    # === Value Iteration ==============================================================================================

    def vi_initialise(self):
        initial_state = self.environment.get_init_state()
        self.state_values = {initial_state: 0}
        self.policy = {initial_state: FORWARD}
        self._explore_states_iterative(initial_state, max_states=10000)

    def _explore_states_iterative(self, initial_state, max_states=10000):
        # Iteratively explore the state space up to a maximum number of states.
        stack = [initial_state]
        explored = set()

        while stack and len(self.state_values) < max_states:
            state = stack.pop()
            if state in explored:
                continue
            explored.add(state)

            for action in BEE_ACTIONS:
                for _, next_state, _ in self.get_transition_outcomes(state, action):
                    if next_state not in self.state_values:
                        self.state_values[next_state] = 0
                        self.policy[next_state] = FORWARD
                        stack.append(next_state)

        if len(self.state_values) >= max_states:
            print(f"Warning: Reached maximum number of states ({max_states})")

    def vi_is_converged(self):
        return all(abs(self.state_values[s] - self._compute_value(s)) < self.epsilon for s in self.state_values)

    def _compute_value(self, state):
        # Compute the value of a state by considering the best possible action.
        if self.environment.is_solved(state):
            return 0
        return max(self._compute_q_value(state, action) for action in BEE_ACTIONS)

    def _compute_q_value(self, state, action):
        # Compute the Q-value for a given state-action pair by summing over all possible outcomes.
        return sum(prob * (reward + self.gamma * self.state_values.get(next_state, 0))
                   for prob, next_state, reward in self.get_transition_outcomes(state, action))

    def vi_iteration(self):
        # Perform one iteration of value iteration, updating the value and policy for each state.
        for state in self.state_values:
            if self.environment.is_solved(state):
                self.state_values[state] = 0
                continue

            best_value = float('-inf')
            best_action = None
            for action in BEE_ACTIONS:
                value = self._compute_q_value(state, action)
                if value > best_value:
                    best_value = value
                    best_action = action

            self.state_values[state] = best_value
            self.policy[state] = best_action

    def vi_plan_offline(self):
        self.vi_initialise()
        iterations = 0
        while not self.vi_is_converged() and iterations < 1000:
            self.vi_iteration()
            iterations += 1

    def vi_get_state_value(self, state: State):
        return self.state_values.get(state, 0)

    def vi_select_action(self, state: State):
        return self.policy.get(state, FORWARD)

    # === Policy Iteration =============================================================================================

    def pi_initialise(self):
        self.vi_initialise()  # Maintain the initial setup from value iteration.
        self.state_list = list(self.state_values.keys())
        self.state_to_index = {state: i for i, state in enumerate(self.state_list)}
        self.value_array = np.array([self.state_values[s] for s in self.state_list])
        self.policy_array = np.array([BEE_ACTIONS.index(self.policy[s]) for s in self.state_list])
        self.is_solved_array = np.array([self.environment.is_solved(s) for s in self.state_list])

    @lru_cache(maxsize=None)
    def _get_transition_matrix(self, action):
        T = np.zeros((len(self.state_list), len(self.state_list)))
        R = np.zeros(len(self.state_list))
        for i, state in enumerate(self.state_list):
            outcomes = self.get_transition_outcomes(state, action)
            for prob, next_state, reward in outcomes:
                j = self.state_to_index.get(next_state, i)  # 如果next_state不在列表中，保持在当前状态
                T[i, j] += prob
                R[i] += prob * reward
        return T, R

    def pi_is_converged(self):
        return self.policy_stable

    def pi_policy_evaluation(self):
        max_iterations = 100
        for _ in range(max_iterations):
            old_value = self.value_array.copy()
            for action in BEE_ACTIONS:
                action_indices = self.policy_array == BEE_ACTIONS.index(action)
                if not np.any(action_indices):
                    continue
                T, R = self._get_transition_matrix(action)
                self.value_array[action_indices] = R[action_indices] + self.gamma * (
                            T[action_indices] @ self.value_array)
            if np.max(np.abs(old_value - self.value_array)) < self.epsilon:
                break

    def pi_policy_improvement(self):
        # Improve the current policy by selecting the best action for each state.
        old_policy = self.policy_array.copy()
        for action in BEE_ACTIONS:
            T, R = self._get_transition_matrix(action)
            Q = R + self.gamma * (T @ self.value_array)
            self.policy_array = np.where(Q > self.value_array, BEE_ACTIONS.index(action), self.policy_array)
        policy_stable = np.all(old_policy == self.policy_array)
        return policy_stable

    def pi_iteration(self):
        # Perform one iteration of policy iteration, evaluating and improving the policy.
        self.pi_policy_evaluation()
        self.pi_policy_evaluation()
        self.policy_stable = self.pi_policy_improvement()

        # Update the dictionary-based state values and policies with the latest values.
        for i, state in enumerate(self.state_list):
            self.state_values[state] = self.value_array[i]
            self.policy[state] = BEE_ACTIONS[self.policy_array[i]]

    def pi_plan_offline(self):
        self.pi_initialise()
        iterations = 0
        while iterations < 100:
            if self.pi_iteration():
                break
            iterations += 1

    def pi_select_action(self, state: State):
        return self.policy.get(state, FORWARD)
