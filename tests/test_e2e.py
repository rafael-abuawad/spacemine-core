"""Full player journey: CREDITS -> SCV -> reveal -> stake -> mine -> spaceship."""

import boa

from helpers import ASH, E18, FRIGATE, KIND_GAS, KIND_MINERAL, SCV_PRICE, fund_credits


def test_full_flow(world, deployer, alice):
    credits, scv, planets, mining, minerals, gas, ships = (
        world.credits,
        world.scv,
        world.planets,
        world.mining,
        world.minerals,
        world.gas,
        world.spaceships,
    )

    # Admin seeds the universe.
    planet = planets.create_planet("Char", ASH, 6, 120, -45, 12_000, 8_000, sender=deployer)
    patch = mining.create_node(planet, KIND_MINERAL, 3, 1_000_000 * E18, E18, sender=deployer)
    geyser = mining.create_node(planet, KIND_GAS, 3, 1_000_000 * E18, E18, sender=deployer)
    frigate = ships.create_ship_type(
        "Valkyrie", FRIGATE, 100 * E18, 50 * E18, 1_000, 300, 120, 60, 60, 200, sender=deployer
    )
    assert planets.nodes_of(planet) == [patch, geyser]
    assert planets.ownerOf(planet) == planets.address

    # 1. Buy SCVs with CREDITS.
    fund_credits(world, alice, 2 * SCV_PRICE)
    first = scv.buy(2, 2 * SCV_PRICE, sender=alice)
    ids = [first, first + 1]
    assert credits.balanceOf(world.treasury) == 2 * SCV_PRICE

    # 2. Reveal after the commit block.
    boa.env.time_travel(blocks=3)
    scv.reveal(ids)
    assert all(scv.is_revealed(i) for i in ids)

    # 3. Stake one SCV per node.
    scv.setApprovalForAll(mining.address, True, sender=alice)
    mining.stake(patch, [ids[0]], sender=alice)
    mining.stake(geyser, [ids[1]], sender=alice)
    assert mining.staked_by(alice) == ids

    # 4. Mine for a while and claim.
    boa.env.time_travel(seconds=600)
    mining.claim(ids, sender=alice)
    mined_minerals, mined_gas = minerals.balanceOf(alice), gas.balanceOf(alice)
    assert 600 * E18 - 1 <= mined_minerals <= 600 * E18
    assert 600 * E18 - 1 <= mined_gas <= 600 * E18
    assert scv.lifetime_minerals(ids[0]) == mined_minerals
    assert scv.lifetime_gas(ids[1]) == mined_gas

    # 5. Buy spaceships with the mined resources (burned).
    minerals.approve(ships.address, 300 * E18, sender=alice)
    gas.approve(ships.address, 150 * E18, sender=alice)
    assert ships.quote(frigate, 3) == (300 * E18, 150 * E18)
    ships.buy(frigate, 3, 300 * E18, 150 * E18, sender=alice)
    assert ships.balanceOf(alice, frigate) == 3
    assert minerals.totalSupply() == mined_minerals - 300 * E18
    assert gas.totalSupply() == mined_gas - 150 * E18

    # 6. Unstake: the SCVs come home with their stats.
    mining.unstake(ids, sender=alice)
    assert [scv.ownerOf(i) for i in ids] == [alice, alice]
    assert scv.lifetime_minerals(ids[0]) == mining.paid_out(patch)
    assert scv.lifetime_gas(ids[1]) == mining.paid_out(geyser)
    assert scv.tokenURI(ids[0]).endswith(f"/scv/{ids[0]}")
    assert ships.uri(frigate).endswith(f"/ships/{frigate}")
