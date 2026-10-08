"""Property-based tests over amounts, weights, and time deltas.

Weights are fuzzed through the real reveal path: a fuzzed block hash is planted in the
EIP-2935 history contract, so every SCV gets fuzzed (but protocol-valid) properties.
"""

import boa
import pytest
from eth_abi import encode
from eth_utils import keccak
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from helpers import (
    HISTORY_ADDRESS,
    HISTORY_CODE,
    KIND_GAS,
    KIND_MINERAL,
    NodeModel,
    expected_roll,
    give_resources,
    now,
)
from script.deploy import deploy

FUZZ = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
HASHES = st.binary(min_size=32, max_size=32).filter(lambda b: b != bytes(32))


@pytest.fixture(scope="module")
def base():
    d = deploy(seed_demo=False)
    d.scv.set_sale_active(True)
    planet = d.planets.create_planet("Fuzzworld", 0, 5, 0, 0, 10_000, 10_000)
    return d, planet


def buy_with_hash(d, user, quantity: int, block_hash: bytes) -> list[int]:
    cost = d.scv.price() * quantity
    d.credits.mint(user, cost)
    d.credits.approve(d.scv.address, cost, sender=user)
    first = d.scv.buy(quantity, cost, sender=user)
    ids = list(range(first, first + quantity))
    commit = d.scv.reveal_block(first)
    boa.env.time_travel(blocks=300)
    boa.env.set_code(HISTORY_ADDRESS, HISTORY_CODE)
    boa.env.set_storage(HISTORY_ADDRESS, commit % 8191, int.from_bytes(block_hash, "big"))
    d.scv.reveal(ids)
    return ids


@FUZZ
@given(block_hash=HASHES, quantity=st.integers(1, 5))
def test_fuzz_reveal_roll(base, block_hash, quantity):
    d, _ = base
    with boa.env.anchor():
        user = boa.env.generate_address()
        ids = buy_with_hash(d, user, quantity, block_hash)
        for token_id in ids:
            props = d.scv.properties(token_id)
            seed = keccak(encode(["bytes32", "uint256", "address"], [block_hash, token_id, d.scv.address]))
            assert props.seed == seed
            assert (props.model, props.mining_power, props.mineral_efficiency_bps, props.gas_efficiency_bps) == (
                expected_roll(seed)
            )
            assert 0 <= props.model <= 3
            assert 100 <= props.mining_power <= 400
            assert 5_000 <= props.mineral_efficiency_bps <= 15_000
            assert 5_000 <= props.gas_efficiency_bps <= 15_000
            assert 50 <= d.scv.mining_weight(token_id, KIND_MINERAL) <= 600
            assert 50 <= d.scv.mining_weight(token_id, KIND_GAS) <= 600


@FUZZ
@given(quantity=st.integers(1, 20), price=st.integers(1, 10**30), slack=st.integers(0, 10**18))
def test_fuzz_scv_buy_cost(base, quantity, price, slack):
    d, _ = base
    with boa.env.anchor():
        user = boa.env.generate_address()
        d.scv.set_price(price)
        cost = price * quantity
        d.credits.mint(user, cost + slack)
        d.credits.approve(d.scv.address, cost + slack, sender=user)
        with boa.reverts("scv: cost exceeds max"):
            d.scv.buy(quantity, cost - 1, sender=user)
        treasury_before = d.credits.balanceOf(d.treasury)
        d.scv.buy(quantity, cost + slack, sender=user)
        assert d.credits.balanceOf(d.treasury) - treasury_before == cost
        assert d.credits.balanceOf(user) == slack
        assert d.scv.balanceOf(user) == quantity


@FUZZ
@given(
    reserve=st.integers(1, 10**27),
    rate=st.integers(1, 10**22),
    kind=st.sampled_from([KIND_MINERAL, KIND_GAS]),
    block_hash=HASHES,
    n_scvs=st.integers(1, 3),
    steps=st.lists(
        st.tuples(st.integers(0, 10**6), st.integers(0, 2), st.sampled_from(["claim", "unstake", "wait"])),
        max_size=8,
    ),
)
def test_fuzz_emission_matches_model(base, reserve, rate, kind, block_hash, n_scvs, steps):
    d, planet = base
    with boa.env.anchor():
        user = boa.env.generate_address()
        ids = buy_with_hash(d, user, n_scvs, block_hash)
        node_id = d.mining.create_node(planet, kind, 3, reserve, rate)
        token = d.minerals if kind == KIND_MINERAL else d.gas
        node = d.mining.node(node_id)
        model = NodeModel(node.reserve_total, rate, node.last_update)

        d.scv.setApprovalForAll(d.mining.address, True, sender=user)
        d.mining.stake(node_id, ids, sender=user)
        for scv_id in ids:
            model.stake(scv_id, d.scv.mining_weight(scv_id, kind), now())
        assert d.mining.node(node_id).total_weight == model.total_weight

        collects = 0
        for delta, index, action in steps:
            boa.env.time_travel(seconds=delta)
            scv_id = ids[index % n_scvs]
            for i in ids:
                if i in model.positions:
                    assert d.mining.pending(i) == model.pending(i, now())
            if action == "wait" or scv_id not in model.positions:
                continue
            expected = model.collect(scv_id, now(), release=action == "unstake")
            before = token.balanceOf(user)
            getattr(d.mining, action)([scv_id], sender=user)
            assert token.balanceOf(user) - before == expected
            collects += 1

        boa.env.time_travel(seconds=10**6)
        remaining = [i for i in ids if i in model.positions]
        for scv_id in remaining:
            model.collect(scv_id, now(), release=True)
            collects += 1
        if remaining:
            d.mining.unstake(remaining, sender=user)

        minted = token.totalSupply()
        emitted = reserve - d.mining.node(node_id).reserve_remaining
        assert minted == model.paid == d.mining.paid_out(node_id)
        assert minted <= emitted <= reserve
        assert emitted - minted <= collects  # < 1 wei of rounding dust per settlement
        assert d.mining.node(node_id).total_weight == 0
        assert all(d.scv.ownerOf(i) == user for i in ids)


@FUZZ
@given(reserve=st.integers(1, 10**27), rate=st.integers(1, 10**24), dt=st.integers(0, 10**8))
def test_fuzz_single_staker_bounds(base, reserve, rate, dt):
    d, planet = base
    with boa.env.anchor():
        user = boa.env.generate_address()
        (scv_id,) = buy_with_hash(d, user, 1, keccak(b"single"))
        node_id = d.mining.create_node(planet, KIND_MINERAL, 1, reserve, rate)
        d.scv.setApprovalForAll(d.mining.address, True, sender=user)
        d.mining.stake(node_id, [scv_id], sender=user)
        boa.env.time_travel(seconds=dt)
        expected = min(rate * dt, reserve)
        pending = d.mining.pending(scv_id)
        assert expected - 1 <= pending <= expected
        assert d.mining.is_depleted(node_id) == (rate * dt >= reserve)
        d.mining.unstake([scv_id], sender=user)
        assert d.minerals.totalSupply() == pending


@FUZZ
@given(
    mineral_cost=st.integers(0, 10**24),
    gas_cost=st.integers(0, 10**24),
    amount=st.integers(1, 50),
    extra=st.integers(0, 10**18),
)
def test_fuzz_spaceship_buy(base, mineral_cost, gas_cost, amount, extra):
    if mineral_cost == 0 and gas_cost == 0:
        mineral_cost = 1
    d, _ = base
    with boa.env.anchor():
        user = boa.env.generate_address()
        ship = d.spaceships.create_ship_type("Fuzz", 2, mineral_cost, gas_cost, 0, 1, 1, 1, 1, 1)
        total_m, total_g = mineral_cost * amount, gas_cost * amount
        give_resources(d, user, minerals=total_m + extra, gas=total_g + extra)
        if total_m:
            with boa.reverts("spaceships: mineral cost exceeds max"):
                d.spaceships.buy(ship, amount, total_m - 1, total_g, sender=user)
        if total_g:
            with boa.reverts("spaceships: gas cost exceeds max"):
                d.spaceships.buy(ship, amount, total_m, total_g - 1, sender=user)
        supply_m, supply_g = d.minerals.totalSupply(), d.gas.totalSupply()
        d.spaceships.buy(ship, amount, total_m, total_g, sender=user)
        assert d.spaceships.balanceOf(user, ship) == amount
        assert d.minerals.totalSupply() == supply_m - total_m
        assert d.gas.totalSupply() == supply_g - total_g
        assert d.minerals.balanceOf(user) == extra and d.gas.balanceOf(user) == extra
        assert d.spaceships.quote(ship, amount) == (total_m, total_g)


@FUZZ
@given(scv_price=st.integers(1, 10**24), quantity=st.integers(1, 20))
def test_fuzz_reveal_window(base, scv_price, quantity):
    """Reveal is impossible up to and including the commit block, always possible after."""
    d, _ = base
    with boa.env.anchor():
        user = boa.env.generate_address()
        d.scv.set_price(scv_price)
        d.credits.mint(user, scv_price * quantity)
        d.credits.approve(d.scv.address, scv_price * quantity, sender=user)
        first = d.scv.buy(quantity, scv_price * quantity, sender=user)
        ids = list(range(first, first + quantity))
        boa.env.time_travel(blocks=2)
        with boa.reverts("scv: reveal too early"):
            d.scv.reveal(ids)
        boa.env.time_travel(blocks=1)
        d.scv.reveal(ids)
        assert all(d.scv.is_revealed(i) for i in ids)
