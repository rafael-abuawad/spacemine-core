import boa
import pytest

from helpers import (
    ASH,
    E18,
    ICE,
    JUNGLE,
    KIND_GAS,
    KIND_MINERAL,
    MAX_UINT256,
    TERRAN,
    NodeModel,
    buy_and_reveal,
    buy_scvs,
    event_names,
    events,
    now,
    stake,
)
from src import mining as Mining
from src import planets as Planets
from src import resource_token as ResourceToken
from src import scv as SCV

RESERVE = 1_000_000 * E18
RATE = E18


@pytest.fixture
def make_node(mining, planet_id, deployer):
    def make(kind=KIND_MINERAL, slots=3, reserve=RESERVE, rate=RATE):
        return mining.create_node(planet_id, kind, slots, reserve, rate, sender=deployer)

    return make


@pytest.fixture
def node_id(make_node):
    return make_node()


def model_for(mining, node_id) -> NodeModel:
    node = mining.node(node_id)
    return NodeModel(node.reserve_total, node.emission_rate, node.last_update)


# ---------------------------------------------------------------------------
# create_node / admin
# ---------------------------------------------------------------------------


def test_create_node_scales_reserve_by_richness(mining, planets, deployer):
    planet = planets.create_planet("Char", ASH, 6, 0, 0, 12_000, 8_000, sender=deployer)
    mineral_node = mining.create_node(planet, KIND_MINERAL, 3, 1_000 * E18, E18, sender=deployer)
    created = events(mining, "NodeCreated")[0]
    gas_node = mining.create_node(planet, KIND_GAS, 2, 1_000 * E18, E18 // 2, sender=deployer)

    assert (mineral_node, gas_node) == (1, 2)
    assert (created.node_id, created.planet_id, created.kind, created.reserve_total) == (
        1,
        planet,
        KIND_MINERAL,
        1_200 * E18,
    )
    assert planets.nodes_of(planet) == [1, 2]
    node = mining.node(mineral_node)
    assert (node.planet_id, node.kind, node.max_slots, node.occupied) == (planet, KIND_MINERAL, 3, 0)
    assert node.reserve_total == node.reserve_remaining == 1_200 * E18
    assert (node.emission_rate, node.total_weight, node.reward_per_weight_stored, node.active) == (E18, 0, 0, True)
    gas = mining.node(gas_node)
    assert (gas.kind, gas.max_slots, gas.reserve_total, gas.emission_rate) == (KIND_GAS, 2, 800 * E18, E18 // 2)
    assert mining.node_count() == 2


@pytest.mark.parametrize(
    "kind,slots,reserve,rate,message",
    [
        (0, 3, RESERVE, RATE, "mining: invalid kind"),  # empty flag
        (KIND_MINERAL | KIND_GAS, 3, RESERVE, RATE, "mining: invalid kind"),
        (KIND_MINERAL, 0, RESERVE, RATE, "mining: invalid slots"),
        (KIND_MINERAL, 9, RESERVE, RATE, "mining: invalid slots"),
        (KIND_MINERAL, 3, 0, RATE, "mining: invalid reserve"),
        (KIND_MINERAL, 3, 10**30 + 1, RATE, "mining: invalid reserve"),
        (KIND_MINERAL, 3, RESERVE, 0, "mining: invalid rate"),
        (KIND_MINERAL, 3, RESERVE, 10**24 + 1, "mining: invalid rate"),
    ],
)
def test_create_node_validation(mining, planet_id, deployer, kind, slots, reserve, rate, message):
    with boa.reverts(message):
        mining.create_node(planet_id, kind, slots, reserve, rate, sender=deployer)


def test_create_node_bounds_accepted(mining, planet_id, deployer):
    mining.create_node(planet_id, KIND_GAS, 8, 10**30, 10**24, sender=deployer)
    mining.create_node(planet_id, KIND_MINERAL, 1, 1, 1, sender=deployer)
    assert mining.node(2).reserve_total == 1


def test_create_node_unknown_planet(mining, deployer):
    with boa.reverts("erc721: invalid token ID"):
        mining.create_node(7, KIND_MINERAL, 3, RESERVE, RATE, sender=deployer)


def test_create_node_zero_richness(mining, planets, deployer):
    planet = planets.create_planet("Barren", ICE, 2, 0, 0, 5_000, 0, sender=deployer)
    with boa.reverts("mining: zero reserve"):
        mining.create_node(planet, KIND_GAS, 3, RESERVE, RATE, sender=deployer)
    with boa.reverts("mining: zero reserve"):  # 1 * 5_000 // 10_000 rounds down to zero
        mining.create_node(planet, KIND_MINERAL, 3, 1, RATE, sender=deployer)


def test_create_node_planet_limit(mining, planet_id, deployer):
    for _ in range(16):
        mining.create_node(planet_id, KIND_MINERAL, 1, E18, 1, sender=deployer)
    with boa.reverts("planets: node limit reached"):
        mining.create_node(planet_id, KIND_MINERAL, 1, E18, 1, sender=deployer)


def test_admin_owner_only(mining, planet_id, node_id, alice):
    for call in (
        lambda: mining.create_node(planet_id, KIND_MINERAL, 3, RESERVE, RATE, sender=alice),
        lambda: mining.set_node_active(node_id, False, sender=alice),
        lambda: mining.pause(sender=alice),
        lambda: mining.unpause(sender=alice),
    ):
        with boa.reverts("ownable: caller is not the owner"):
            call()


def test_set_node_active(mining, node_id, deployer):
    mining.set_node_active(node_id, False, sender=deployer)
    assert [tuple(log)[1:] for log in events(mining, "NodeActiveUpdated")] == [(node_id, False)]
    assert mining.node(node_id).active is False
    with boa.reverts("mining: unknown node"):
        mining.set_node_active(99, False, sender=deployer)
    with boa.reverts("mining: unknown node"):
        mining.set_node_active(0, False, sender=deployer)


def test_pause_unpause(mining, deployer):
    mining.pause(sender=deployer)
    assert mining.paused() is True
    with boa.reverts("pausable: contract is paused"):
        mining.pause(sender=deployer)
    mining.unpause(sender=deployer)
    assert mining.paused() is False
    with boa.reverts("pausable: contract is not paused"):
        mining.unpause(sender=deployer)


def test_no_privileged_escape_hatches(mining):
    names = {item["name"] for item in mining.abi if item["type"] == "function"}
    mutating = {item["name"] for item in mining.abi if item["type"] == "function" and item["stateMutability"] != "view"}
    assert mutating == {
        "create_node",
        "set_node_active",
        "pause",
        "unpause",
        "stake",
        "unstake",
        "claim",
        "onERC721Received",
        "transfer_ownership",
        "accept_ownership",
        "renounce_ownership",
    }
    assert "set_reserve" not in names and "rescue" not in names


# ---------------------------------------------------------------------------
# stake
# ---------------------------------------------------------------------------


def test_stake_escrows_and_records(world, mining, scv, node_id, alice):
    ids = buy_and_reveal(world, alice, 2)
    weights = [scv.mining_weight(i, KIND_MINERAL) for i in ids]
    stake(world, alice, node_id, ids)
    staked = events(mining, "Staked")

    assert [(log.owner, log.node_id, log.scv_id, log.weight) for log in staked] == [
        (alice, node_id, ids[0], weights[0]),
        (alice, node_id, ids[1], weights[1]),
    ]
    for scv_id, weight in zip(ids, weights, strict=False):
        assert scv.ownerOf(scv_id) == mining.address
        position = mining.position(scv_id)
        assert (position.node_id, position.owner, position.weight) == (node_id, alice, weight)
        assert (position.reward_per_weight_paid, position.accrued) == (0, 0)
    node = mining.node(node_id)
    assert (node.occupied, node.total_weight) == (2, sum(weights))
    assert mining.node_scvs(node_id) == ids
    assert mining.staked_by(alice) == ids


def test_stake_weight_uses_node_kind(world, mining, scv, make_node, alice):
    gas_node = make_node(kind=KIND_GAS)
    (scv_id,) = buy_and_reveal(world, alice, 1)
    stake(world, alice, gas_node, [scv_id])
    assert mining.position(scv_id).weight == scv.mining_weight(scv_id, KIND_GAS)
    props = scv.properties(scv_id)
    assert mining.position(scv_id).weight == props.mining_power * props.gas_efficiency_bps // 10_000


def test_stake_slot_cap(world, mining, node_id, alice, bob):
    ids = buy_and_reveal(world, alice, 4)
    with boa.reverts("mining: node full"):
        stake(world, alice, node_id, ids)
    stake(world, alice, node_id, ids[:2])
    with boa.reverts("mining: node full"):
        mining.stake(node_id, ids[2:], sender=alice)
    mining.stake(node_id, ids[2:3], sender=alice)
    assert mining.node(node_id).occupied == 3
    (other,) = buy_and_reveal(world, bob, 1)
    with boa.reverts("mining: node full"):
        stake(world, bob, node_id, [other])


def test_stake_reverts(world, mining, scv, node_id, alice, bob, deployer):
    ids = buy_and_reveal(world, alice, 2)
    (unrevealed,) = buy_scvs(world, alice, 1)
    scv.setApprovalForAll(mining.address, True, sender=alice)

    with boa.reverts("mining: empty batch"):
        mining.stake(node_id, [], sender=alice)
    with boa.reverts("mining: unknown node"):
        mining.stake(42, ids[:1], sender=alice)
    with boa.reverts("mining: not scv owner"):
        mining.stake(node_id, ids[:1], sender=bob)
    with boa.reverts("mining: already staked"):
        mining.stake(node_id, [ids[0], ids[0]], sender=alice)
    with boa.reverts("mining: scv not revealed"):
        mining.stake(node_id, [unrevealed], sender=alice)

    mining.pause(sender=deployer)
    with boa.reverts("pausable: contract is paused"):
        mining.stake(node_id, ids[:1], sender=alice)
    mining.unpause(sender=deployer)

    mining.set_node_active(node_id, False, sender=deployer)
    with boa.reverts("mining: node inactive"):
        mining.stake(node_id, ids[:1], sender=alice)
    mining.set_node_active(node_id, True, sender=deployer)

    mining.stake(node_id, ids[:1], sender=alice)
    with boa.reverts("mining: not scv owner"):  # escrowed SCVs belong to Mining
        mining.stake(node_id, ids[:1], sender=alice)


def test_stake_requires_approval(world, mining, node_id, alice):
    ids = buy_and_reveal(world, alice, 1)
    with boa.reverts("erc721: caller is not token owner or approved"):
        mining.stake(node_id, ids, sender=alice)


def test_owner_stake_limit(world, mining, scv, planets, deployer, alice):
    planet = planets.create_planet("Hive", JUNGLE, 10, 0, 0, 10_000, 10_000, sender=deployer)
    nodes = [mining.create_node(planet, KIND_MINERAL, 8, RESERVE, RATE, sender=deployer) for _ in range(16)]
    ids = []
    for _ in range(6):
        ids += buy_scvs(world, alice, 20)
    ids += buy_scvs(world, alice, 9)  # 129 SCVs (revealed with baseline stats below)
    boa.env.time_travel(blocks=300)
    for start in range(0, len(ids), 50):
        scv.reveal(ids[start : start + 50])
    scv.setApprovalForAll(mining.address, True, sender=alice)
    for index, node in enumerate(nodes):
        mining.stake(node, ids[index * 8 : index * 8 + 8], sender=alice)
    assert len(mining.staked_by(alice)) == 128
    other_planet = planets.create_planet("Overflow", JUNGLE, 10, 1, 1, 10_000, 10_000, sender=deployer)
    overflow_node = mining.create_node(other_planet, KIND_MINERAL, 1, RESERVE, RATE, sender=deployer)
    with boa.reverts("mining: owner stake limit"):
        mining.stake(overflow_node, [ids[128]], sender=alice)


def test_wiring_checks(credits, deployer, alice):
    planets = Planets.deploy("", "", "")
    scv = SCV.deploy(credits.address, deployer, False, 1, 100, "", "", "")
    minerals = ResourceToken.deploy("Spacemine Minerals", "MNRL")
    gas = ResourceToken.deploy("Spacemine Gas", "GAS")
    mining = Mining.deploy(scv.address, planets.address, minerals.address, gas.address)
    planets.set_mining(mining.address)
    planet = planets.create_planet("Wired", TERRAN, 1, 0, 0, 10_000, 10_000)
    node = mining.create_node(planet, KIND_MINERAL, 3, RESERVE, RATE)

    with boa.reverts("mining: scv not wired"):
        mining.stake(node, [1], sender=alice)
    scv.set_mining(mining.address)
    with boa.reverts("mining: not minter"):
        mining.stake(node, [1], sender=alice)
    minerals.set_mining(mining.address)
    with boa.reverts("mining: not minter"):
        mining.stake(node, [1], sender=alice)
    gas.set_mining(mining.address)
    with boa.reverts("erc721: invalid token ID"):  # passes the wiring checks, fails on the missing token
        mining.stake(node, [1], sender=alice)


@pytest.mark.parametrize("zero_index", range(4))
def test_constructor_rejects_zero_addresses(world, zero_index):
    args = [world.scv.address, world.planets.address, world.minerals.address, world.gas.address]
    args[zero_index] = "0x0000000000000000000000000000000000000000"
    with boa.reverts("mining: zero address"):
        Mining.deploy(*args)


def test_safe_transfer_into_mining_rejected(world, mining, scv, alice):
    (scv_id,) = buy_and_reveal(world, alice, 1)
    with boa.reverts("mining: use stake"):
        scv.safeTransferFrom(alice, mining.address, scv_id, sender=alice)
    assert scv.ownerOf(scv_id) == alice


# ---------------------------------------------------------------------------
# Emission math
# ---------------------------------------------------------------------------


def test_single_staker_payout(world, mining, scv, minerals, node_id, alice):
    (scv_id,) = buy_and_reveal(world, alice, 1)
    model = model_for(mining, node_id)
    stake(world, alice, node_id, [scv_id])
    model.stake(scv_id, mining.position(scv_id).weight, now())

    boa.env.time_travel(seconds=100)
    expected = model.pending(scv_id, now())
    assert mining.pending(scv_id) == expected
    assert 100 * RATE - 1 <= expected <= 100 * RATE

    mining.claim([scv_id], sender=alice)
    claimed = events(mining, "Claimed")
    assert [(log.owner, log.node_id, log.scv_id, log.reward) for log in claimed] == [(alice, node_id, scv_id, expected)]
    assert minerals.balanceOf(alice) == expected
    assert scv.lifetime_minerals(scv_id) == expected
    assert scv.lifetime_gas(scv_id) == 0
    assert mining.pending(scv_id) == 0
    assert mining.paid_out(node_id) == expected
    assert scv.ownerOf(scv_id) == mining.address  # claim does not unstake


def test_claim_same_block_twice_pays_nothing_more(world, mining, minerals, node_id, alice):
    (scv_id,) = buy_and_reveal(world, alice, 1)
    stake(world, alice, node_id, [scv_id])
    boa.env.time_travel(seconds=10)
    mining.claim([scv_id], sender=alice)
    balance = minerals.balanceOf(alice)
    mining.claim([scv_id], sender=alice)
    assert minerals.balanceOf(alice) == balance
    assert "LifetimeStatsUpdated" not in event_names(world.scv)


def test_gas_node_pays_gas(world, mining, scv, minerals, gas, make_node, alice):
    gas_node = make_node(kind=KIND_GAS, rate=3 * E18)
    (scv_id,) = buy_and_reveal(world, alice, 1)
    stake(world, alice, gas_node, [scv_id])
    boa.env.time_travel(seconds=50)
    pending = mining.pending(scv_id)
    mining.unstake([scv_id], sender=alice)
    assert gas.balanceOf(alice) == pending
    assert minerals.balanceOf(alice) == 0
    assert scv.lifetime_gas(scv_id) == pending
    assert scv.ownerOf(scv_id) == alice


def test_pro_rata_payouts(world, mining, scv, minerals, node_id, alice, bob):
    alice_ids = buy_scvs(world, alice, 2)
    bob_ids = buy_scvs(world, bob, 1)
    boa.env.time_travel(blocks=3)
    scv.reveal(alice_ids + bob_ids)

    model = model_for(mining, node_id)
    stake(world, alice, node_id, alice_ids)
    stake(world, bob, node_id, bob_ids)
    for scv_id in alice_ids + bob_ids:
        model.stake(scv_id, mining.position(scv_id).weight, now())

    boa.env.time_travel(seconds=1_000)
    expected = {scv_id: model.pending(scv_id, now()) for scv_id in alice_ids + bob_ids}
    assert mining.pending_many(alice_ids + bob_ids) == [expected[i] for i in alice_ids + bob_ids]

    total_weight = mining.node(node_id).total_weight
    for scv_id, amount in expected.items():
        exact = 1_000 * RATE * mining.position(scv_id).weight // total_weight
        assert exact - 1 <= amount <= exact

    mining.claim(alice_ids, sender=alice)
    mining.claim(bob_ids, sender=bob)
    assert minerals.balanceOf(alice) == sum(expected[i] for i in alice_ids)
    assert minerals.balanceOf(bob) == expected[bob_ids[0]]
    assert sum(expected.values()) <= 1_000 * RATE


def test_join_and_leave_midstream(world, mining, scv, minerals, node_id, alice, bob):
    alice_ids = buy_scvs(world, alice, 1)
    bob_ids = buy_scvs(world, bob, 1)
    boa.env.time_travel(blocks=3)
    scv.reveal(alice_ids + bob_ids)
    a, b = alice_ids[0], bob_ids[0]
    model = model_for(mining, node_id)

    stake(world, alice, node_id, [a])
    model.stake(a, mining.position(a).weight, now())
    boa.env.time_travel(seconds=300)

    stake(world, bob, node_id, [b])
    model.stake(b, mining.position(b).weight, now())
    boa.env.time_travel(seconds=200)

    expected_a = model.collect(a, now(), release=True)
    mining.unstake([a], sender=alice)
    unstaked = events(mining, "Unstaked")
    assert [(log.scv_id, log.reward) for log in unstaked] == [(a, expected_a)]
    assert minerals.balanceOf(alice) == expected_a
    assert scv.ownerOf(a) == alice
    assert mining.position(a).node_id == 0

    boa.env.time_travel(seconds=100)
    expected_b = model.collect(b, now(), release=True)
    mining.unstake([b], sender=bob)
    assert minerals.balanceOf(bob) == expected_b

    w_a, w_b = scv.mining_weight(a, KIND_MINERAL), scv.mining_weight(b, KIND_MINERAL)
    assert abs(expected_a - (300 * RATE + 200 * RATE * w_a // (w_a + w_b))) <= 2
    assert abs(expected_b - (200 * RATE * w_b // (w_a + w_b) + 100 * RATE)) <= 2
    assert mining.node(node_id).total_weight == 0
    assert mining.node(node_id).occupied == 0


def test_emission_pauses_without_weight(world, mining, scv, node_id, alice):
    boa.env.time_travel(seconds=10_000)
    node = mining.node(node_id)
    assert node.reserve_remaining == RESERVE
    assert mining.time_to_depletion(node_id) == MAX_UINT256

    (scv_id,) = buy_and_reveal(world, alice, 1)
    stake(world, alice, node_id, [scv_id])
    boa.env.time_travel(seconds=10)
    assert 10 * RATE - 1 <= mining.pending(scv_id) <= 10 * RATE

    mining.unstake([scv_id], sender=alice)
    remaining = mining.node(node_id).reserve_remaining
    boa.env.time_travel(seconds=10_000)
    assert mining.node(node_id).reserve_remaining == remaining == RESERVE - 10 * RATE


def test_exact_depletion(world, mining, scv, minerals, planet_id, deployer, alice, bob):
    reserve, rate = 1_000_003, 997
    node_id = mining.create_node(planet_id, KIND_MINERAL, 3, reserve, rate, sender=deployer)
    alice_ids = buy_scvs(world, alice, 2)
    bob_ids = buy_scvs(world, bob, 1)
    boa.env.time_travel(blocks=3)
    scv.reveal(alice_ids + bob_ids)
    stake(world, alice, node_id, alice_ids)
    stake(world, bob, node_id, bob_ids)

    assert mining.time_to_depletion(node_id) == (reserve + rate - 1) // rate
    boa.env.time_travel(seconds=reserve // rate + 50)
    assert mining.is_depleted(node_id) is True
    assert mining.time_to_depletion(node_id) == 0

    mining.unstake(alice_ids, sender=alice)
    assert "NodeDepleted" in event_names(mining)
    mining.unstake(bob_ids, sender=bob)
    assert "NodeDepleted" not in event_names(mining)  # emitted exactly once

    minted = minerals.totalSupply()
    assert minted == mining.paid_out(node_id)
    assert reserve - 3 <= minted <= reserve
    assert mining.node(node_id).reserve_remaining == 0


def test_depleted_node_rejects_stake_but_allows_claim(world, mining, scv, minerals, planet_id, deployer, alice, bob):
    node_id = mining.create_node(planet_id, KIND_MINERAL, 3, 1_000, 10, sender=deployer)
    (a,) = buy_and_reveal(world, alice, 1)
    stake(world, alice, node_id, [a])
    boa.env.time_travel(seconds=1_000)

    mining.claim([a], sender=alice)
    assert minerals.balanceOf(alice) == mining.paid_out(node_id)
    assert 999 <= minerals.balanceOf(alice) <= 1_000
    boa.env.time_travel(seconds=1_000)
    mining.claim([a], sender=alice)
    assert minerals.balanceOf(alice) == mining.paid_out(node_id) <= 1_000

    (b,) = buy_and_reveal(world, bob, 1)
    with boa.reverts("mining: node depleted"):
        stake(world, bob, node_id, [b])
    mining.unstake([a], sender=alice)
    assert scv.ownerOf(a) == alice


def test_unstake_never_blocked(world, mining, scv, minerals, node_id, alice, deployer):
    ids = buy_and_reveal(world, alice, 2)
    stake(world, alice, node_id, ids)
    boa.env.time_travel(seconds=20)
    mining.pause(sender=deployer)
    mining.set_node_active(node_id, False, sender=deployer)

    mining.claim(ids[:1], sender=alice)
    mining.unstake(ids, sender=alice)
    assert [scv.ownerOf(i) for i in ids] == [alice, alice]
    assert minerals.balanceOf(alice) == mining.paid_out(node_id) > 0


def test_unstake_and_claim_reverts(world, mining, node_id, alice, bob):
    ids = buy_and_reveal(world, alice, 1)
    stake(world, alice, node_id, ids)
    for fn in (mining.unstake, mining.claim):
        with boa.reverts("mining: empty batch"):
            fn([], sender=alice)
        with boa.reverts("mining: not staked"):
            fn([999], sender=alice)
        with boa.reverts("mining: not position owner"):
            fn(ids, sender=bob)
    with boa.reverts("mining: not staked"):
        mining.unstake([ids[0], ids[0]], sender=alice)


def test_staked_scv_cannot_be_moved_by_staker(world, mining, scv, node_id, alice, bob):
    ids = buy_and_reveal(world, alice, 1)
    stake(world, alice, node_id, ids)
    with boa.reverts("erc721: caller is not token owner or approved"):
        scv.transferFrom(mining.address, bob, ids[0], sender=alice)


def test_swap_and_pop_bookkeeping(world, mining, make_node, alice):
    node_a = make_node(slots=8)
    node_b = make_node(slots=8)
    ids = buy_and_reveal(world, alice, 5)
    stake(world, alice, node_a, ids[:3])
    stake(world, alice, node_b, ids[3:])
    mining.unstake([ids[1]], sender=alice)
    assert sorted(mining.node_scvs(node_a)) == [ids[0], ids[2]]
    assert sorted(mining.staked_by(alice)) == sorted([ids[0], ids[2], ids[3], ids[4]])
    mining.unstake([ids[4], ids[0]], sender=alice)
    assert mining.node_scvs(node_a) == [ids[2]]
    assert mining.node_scvs(node_b) == [ids[3]]
    assert sorted(mining.staked_by(alice)) == sorted([ids[2], ids[3]])
    mining.unstake([ids[2], ids[3]], sender=alice)
    assert mining.staked_by(alice) == []
    assert mining.node(node_a).occupied == mining.node(node_b).occupied == 0


def test_mixed_kind_batch_claim(world, mining, minerals, gas, make_node, alice):
    mineral_node = make_node(kind=KIND_MINERAL)
    gas_node = make_node(kind=KIND_GAS)
    ids = buy_and_reveal(world, alice, 2)
    stake(world, alice, mineral_node, ids[:1])
    stake(world, alice, gas_node, ids[1:])
    boa.env.time_travel(seconds=30)
    pending = mining.pending_many(ids)
    mining.claim(ids, sender=alice)
    assert minerals.balanceOf(alice) == pending[0]
    assert gas.balanceOf(alice) == pending[1]


def test_restake_after_unstake(world, mining, node_id, alice):
    ids = buy_and_reveal(world, alice, 1)
    stake(world, alice, node_id, ids)
    mining.unstake(ids, sender=alice)
    mining.stake(node_id, ids, sender=alice)
    assert mining.position(ids[0]).owner == alice


def test_views(world, mining, node_id, alice):
    with boa.reverts("mining: unknown node"):
        mining.node(0)
    with boa.reverts("mining: unknown node"):
        mining.is_depleted(5)
    with boa.reverts("mining: unknown node"):
        mining.time_to_depletion(5)
    assert mining.pending(1) == 0
    assert mining.position(1).node_id == 0
    assert mining.pending_many([1, 2]) == [0, 0]
    assert mining.node_scvs(node_id) == []
    assert mining.is_depleted(node_id) is False

    ids = buy_and_reveal(world, alice, 1)
    stake(world, alice, node_id, ids)
    assert mining.time_to_depletion(node_id) == RESERVE // RATE
    boa.env.time_travel(seconds=60)
    node = mining.node(node_id)
    assert node.reserve_remaining == RESERVE - 60 * RATE  # projected to now
    assert node.last_update == now()
    assert mining.time_to_depletion(node_id) == RESERVE // RATE - 60
