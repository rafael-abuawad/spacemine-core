"""The deploy script wires roles correctly and seeds the local demo."""

import pytest

import script.deploy as deploy_script
from helpers import DEAD_ADDRESS, E18, KIND_GAS, KIND_MINERAL, load_mock


def test_wiring(world, deployer):
    mining = world.mining.address
    for token in (world.minerals, world.gas):
        assert token.is_minter(mining) is True
        assert token.is_minter(deployer) is False
        assert token.mining() == mining
    assert world.scv.mining() == mining
    assert world.planets.mining() == mining
    assert world.mining.scv() == world.scv.address
    assert world.mining.planets() == world.planets.address
    assert world.mining.minerals() == world.minerals.address
    assert world.mining.gas() == world.gas.address
    assert world.spaceships.minerals() == world.minerals.address
    assert world.spaceships.gas() == world.gas.address
    assert world.spaceships.treasury() == world.treasury == deployer


def test_demo_seed():
    d = deploy_script.deploy(seed_demo=True)
    assert d.planets.planet_count() == 1
    assert d.planets.nodes_of(1) == [1, 2, 3]
    kinds = [d.mining.node(i).kind for i in (1, 2, 3)]
    assert kinds == [KIND_MINERAL, KIND_MINERAL, KIND_GAS]
    assert d.spaceships.ship_type_count() == 3
    fighter, frigate, cruiser = (d.spaceships.ship_type(i) for i in (1, 2, 3))
    assert (fighter.mineral_cost > 0, fighter.gas_cost) == (True, 0)
    assert frigate.mineral_cost > 0 and frigate.gas_cost > 0
    assert cruiser.gas_cost > cruiser.mineral_cost
    assert d.planets.planet(1).mineral_richness_bps == 12_000
    assert d.mining.node(1).reserve_total == 1_800_000 * E18


def test_env_configuration(monkeypatch, alice):
    existing = load_mock("MockCredits")
    monkeypatch.setenv("CREDITS_ADDRESS", str(existing.address))
    monkeypatch.setenv("TREASURY_ADDRESS", str(alice))
    monkeypatch.setenv("SCV_BURN_PROCEEDS", "1")
    monkeypatch.setenv("SCV_PRICE", str(7 * E18))
    monkeypatch.setenv("SCV_MAX_SUPPLY", "42")
    monkeypatch.setenv("SCV_BASE_URI", "web3://custom/scv/")
    monkeypatch.setenv("METADATA_SUFFIX", ".json")
    monkeypatch.setenv("ROYALTY_BPS", "0")
    d = deploy_script.deploy(seed_demo=False, verbose=True)
    assert d.credits.address == existing.address
    assert d.scv.credits() == existing.address
    assert d.scv.burn_proceeds() is True
    assert d.scv.BURN_ADDRESS() == DEAD_ADDRESS
    assert (d.scv.price(), d.scv.max_supply()) == (7 * E18, 42)
    assert d.scv.metadata_base() == "web3://custom/scv/"
    assert d.scv.metadata_suffix() == ".json"
    assert d.spaceships.treasury() == alice
    assert d.scv.royaltyInfo(1, 10_000)[1] == 0


def test_live_network_requires_credits(monkeypatch):
    monkeypatch.delenv("CREDITS_ADDRESS", raising=False)
    monkeypatch.setattr(deploy_script, "_is_local", lambda: False)
    with pytest.raises(ValueError, match="CREDITS_ADDRESS"):
        deploy_script.deploy()


def test_moccasin_main(monkeypatch):
    monkeypatch.setenv("SEED_DEMO", "0")
    d = deploy_script.moccasin_main()
    assert d.planets.planet_count() == 0
