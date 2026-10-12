"""The deploy script wires roles correctly and seeds the local demo."""

import pytest

import script.deploy as deploy_script
from helpers import DEAD_ADDRESS, E18, load_mock


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
    seed = deploy_script.load_seed()
    d = deploy_script.deploy(seed_demo=True)
    assert d.planets.planet_count() == len(seed["planets"]) >= 6
    assert {d.planets.planet(i + 1).biome for i in range(len(seed["planets"]))} == set(deploy_script.BIOMES.values())

    node_id = 0
    for index, world in enumerate(seed["planets"]):
        planet_id = index + 1
        planet = d.planets.planet(planet_id)
        assert (planet.name, planet.mineral_richness_bps) == (world["name"], world["mineral_richness_bps"])
        kinds = [node["kind"] for node in world["nodes"]]
        # Every world has several mineral patches and at least one geyser.
        assert kinds.count("MINERAL") >= 2 and kinds.count("GAS") >= 1
        ids = list(range(node_id + 1, node_id + 1 + len(world["nodes"])))
        assert d.planets.nodes_of(planet_id) == ids
        for nid, node in zip(ids, world["nodes"]):
            created = d.mining.node(nid)
            richness = planet.mineral_richness_bps if node["kind"] == "MINERAL" else planet.gas_richness_bps
            assert created.kind == deploy_script.KINDS[node["kind"]]
            assert created.max_slots == node["slots"]
            assert created.emission_rate == deploy_script._wei(node["rate"])
            assert created.reserve_total == deploy_script._wei(node["base_reserve"]) * richness // 10_000
        node_id = ids[-1]
    assert d.mining.node_count() == node_id

    assert d.spaceships.ship_type_count() == len(seed["ships"])
    classes = {d.spaceships.ship_type(i + 1).ship_class for i in range(len(seed["ships"]))}
    assert classes == set(deploy_script.SHIP_CLASSES.values())
    fighter = d.spaceships.ship_type(1)
    assert (fighter.mineral_cost, fighter.gas_cost) == (500 * E18, 0)
    assert d.planets.planet(1).mineral_richness_bps == 11_000
    assert d.mining.node(1).reserve_total == 3_300_000 * E18


def test_live_network_seed_is_opt_in(monkeypatch):
    monkeypatch.setattr(deploy_script, "_is_local", lambda: False)
    monkeypatch.setenv("CREDITS_ADDRESS", str(load_mock("mock_credits").address))
    monkeypatch.delenv("SEED_DEMO", raising=False)
    assert deploy_script.deploy().planets.planet_count() == 0
    monkeypatch.setenv("SEED_DEMO", "1")
    assert deploy_script.deploy().planets.planet_count() == len(deploy_script.load_seed()["planets"])


def test_env_configuration(monkeypatch, alice):
    existing = load_mock("mock_credits")
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
