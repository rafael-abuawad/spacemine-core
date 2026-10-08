"""Stateful invariant test: random stake / unstake / claim / warp sequences against Mining."""

import boa
import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule, run_state_machine_as_test

from helpers import KIND_GAS, KIND_MINERAL
from script.deploy import deploy

N_USERS = 3
SCVS_PER_USER = 4
# Small reserves so that depletion happens within a run.
NODE_SPECS = [  # kind, slots, base_reserve, rate
    (KIND_MINERAL, 3, 5_000_000, 1_000),
    (KIND_MINERAL, 2, 10**21, 10**15),
    (KIND_GAS, 3, 2_000_000, 3_000),
]


@pytest.fixture(scope="module")
def base():
    """Deployed once, outside the per-test isolation; every example runs inside its own anchor."""
    d = deploy(seed_demo=False)
    d.scv.set_sale_active(True)
    planet = d.planets.create_planet("Invariant", 0, 5, 0, 0, 10_000, 10_000)
    nodes = [d.mining.create_node(planet, *spec) for spec in NODE_SPECS]
    users = [boa.env.generate_address(f"user{i}") for i in range(N_USERS)]
    owned = {}
    for user in users:
        cost = d.scv.price() * SCVS_PER_USER
        d.credits.mint(user, cost)
        d.credits.approve(d.scv.address, cost, sender=user)
        first = d.scv.buy(SCVS_PER_USER, cost, sender=user)
        owned[user] = list(range(first, first + SCVS_PER_USER))
        d.scv.setApprovalForAll(d.mining.address, True, sender=user)
    boa.env.time_travel(blocks=3)
    d.scv.reveal([i for ids in owned.values() for i in ids])
    return {"d": d, "nodes": nodes, "users": users, "owned": owned}


class MiningMachine(RuleBasedStateMachine):
    base: dict = {}

    def __init__(self):
        super().__init__()
        base = self.base
        self.d = base["d"]
        self.nodes = base["nodes"]
        self.users = base["users"]
        self.owned = base["owned"]
        self.owner_of = {scv: user for user, ids in self.owned.items() for scv in ids}
        self.staked: dict[int, int] = {}  # scv_id -> node_id
        self._anchor = boa.env.anchor()
        self._anchor.__enter__()

    def teardown(self):
        self._anchor.__exit__(None, None, None)

    # ------------------------------------------------------------------ rules

    @rule(scv_index=st.integers(0, N_USERS * SCVS_PER_USER - 1), node_index=st.integers(0, len(NODE_SPECS) - 1))
    def stake(self, scv_index, node_index):
        scv_id = sorted(self.owner_of)[scv_index]
        node_id = self.nodes[node_index]
        user = self.owner_of[scv_id]
        node = self.d.mining.node(node_id)
        # Mirrors the check order in `Mining.stake`: node-level checks first, then per-SCV checks.
        if node.reserve_remaining == 0:
            with boa.reverts("mining: node depleted"):
                self.d.mining.stake(node_id, [scv_id], sender=user)
        elif node.occupied == node.max_slots:
            with boa.reverts("mining: node full"):
                self.d.mining.stake(node_id, [scv_id], sender=user)
        elif scv_id in self.staked:
            with boa.reverts("mining: not scv owner"):
                self.d.mining.stake(node_id, [scv_id], sender=user)
        else:
            self.d.mining.stake(node_id, [scv_id], sender=user)
            self.staked[scv_id] = node_id

    @rule(scv_index=st.integers(0, N_USERS * SCVS_PER_USER - 1))
    def unstake(self, scv_index):
        scv_id = sorted(self.owner_of)[scv_index]
        user = self.owner_of[scv_id]
        if scv_id not in self.staked:
            with boa.reverts("mining: not staked"):
                self.d.mining.unstake([scv_id], sender=user)
            return
        pending = self.d.mining.pending(scv_id)
        token = self._token_for(self.staked[scv_id])
        before = token.balanceOf(user)
        self.d.mining.unstake([scv_id], sender=user)
        assert token.balanceOf(user) - before == pending
        assert self.d.scv.ownerOf(scv_id) == user
        del self.staked[scv_id]

    @rule(scv_index=st.integers(0, N_USERS * SCVS_PER_USER - 1))
    def claim(self, scv_index):
        scv_id = sorted(self.owner_of)[scv_index]
        user = self.owner_of[scv_id]
        if scv_id not in self.staked:
            with boa.reverts("mining: not staked"):
                self.d.mining.claim([scv_id], sender=user)
            return
        pending = self.d.mining.pending(scv_id)
        token = self._token_for(self.staked[scv_id])
        before = token.balanceOf(user)
        self.d.mining.claim([scv_id], sender=user)
        assert token.balanceOf(user) - before == pending
        assert self.d.mining.pending(scv_id) == 0

    @rule(user_index=st.integers(0, N_USERS - 1))
    def stranger_cannot_touch(self, user_index):
        stranger = self.users[user_index]
        foreign = [s for s in self.staked if self.owner_of[s] != stranger]
        if foreign:
            with boa.reverts("mining: not position owner"):
                self.d.mining.unstake(foreign[:1], sender=stranger)

    @rule(seconds=st.integers(0, 5_000))
    def warp(self, seconds):
        boa.env.time_travel(seconds=seconds)

    @rule(paused=st.booleans(), active=st.booleans(), node_index=st.integers(0, len(NODE_SPECS) - 1))
    def admin(self, paused, active, node_index):
        if paused != self.d.mining.paused():
            (self.d.mining.pause if paused else self.d.mining.unpause)()
        self.d.mining.set_node_active(self.nodes[node_index], active)
        # Admin actions never block exits.
        if self.staked:
            scv_id = next(iter(self.staked))
            self.d.mining.claim([scv_id], sender=self.owner_of[scv_id])
        if self.d.mining.paused():
            self.d.mining.unpause()
        self.d.mining.set_node_active(self.nodes[node_index], True)

    # ------------------------------------------------------------- invariants

    def _token_for(self, node_id):
        return self.d.minerals if self.d.mining.node(node_id).kind == KIND_MINERAL else self.d.gas

    @invariant()
    def reserve_never_exceeded(self):
        for node_id in self.nodes:
            node = self.d.mining.node(node_id)
            pending = sum(self.d.mining.pending(s) for s in self.d.mining.node_scvs(node_id))
            paid = self.d.mining.paid_out(node_id)
            emitted = node.reserve_total - node.reserve_remaining
            assert paid + pending <= emitted <= node.reserve_total

    @invariant()
    def slots_consistent(self):
        for node_id in self.nodes:
            node = self.d.mining.node(node_id)
            scvs = self.d.mining.node_scvs(node_id)
            assert node.occupied == len(scvs) <= node.max_slots
            assert sorted(scvs) == sorted(s for s, n in self.staked.items() if n == node_id)

    @invariant()
    def weights_sum(self):
        for node_id in self.nodes:
            scvs = self.d.mining.node_scvs(node_id)
            assert sum(self.d.mining.position(s).weight for s in scvs) == self.d.mining.node(node_id).total_weight

    @invariant()
    def escrow_matches_positions(self):
        mining = self.d.mining.address
        for scv_id, user in self.owner_of.items():
            position = self.d.mining.position(scv_id)
            holder = self.d.scv.ownerOf(scv_id)
            if holder == mining:
                assert position.node_id != 0 and position.owner == user
                assert scv_id in self.d.mining.node_scvs(position.node_id)
                assert self.d.mining.staked_by(user).count(scv_id) == 1
            else:
                assert holder == user
                assert position.node_id == 0
        for user in self.users:
            for scv_id in self.d.mining.staked_by(user):
                assert self.d.scv.ownerOf(scv_id) == mining

    @invariant()
    def resource_supply_matches_payouts(self):
        paid = {KIND_MINERAL: 0, KIND_GAS: 0}
        for node_id, (kind, *_) in zip(self.nodes, NODE_SPECS, strict=True):
            paid[kind] += self.d.mining.paid_out(node_id)
        assert self.d.minerals.totalSupply() == paid[KIND_MINERAL]
        assert self.d.gas.totalSupply() == paid[KIND_GAS]


def test_mining_invariants(base):
    MiningMachine.base = base
    run_state_machine_as_test(
        MiningMachine,
        settings=settings(
            max_examples=30,
            stateful_step_count=40,
            deadline=None,
            suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
        ),
    )
