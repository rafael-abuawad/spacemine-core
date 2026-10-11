"""tokenURI / uri / contractURI strings and their refresh events for all three collections."""

import boa

from helpers import (
    FIGHTER,
    MAX_UINT256,
    PLANETS_BASE,
    RENDERER,
    SCV_BASE,
    SHIPS_BASE,
    TERRAN,
    buy_scvs,
    event_names,
    events,
    log_args,
)
from src import planets as Planets
from src import scv as SCV
from src import spaceships as Spaceships

NEW_BASE = "web3://0x2222222222222222222222222222222222222222:8453/v2/"


def test_scv_token_uri(world, scv, alice):
    buy_scvs(world, alice, 12)
    assert scv.metadata_base() == SCV_BASE
    assert scv.metadata_suffix() == ""
    assert scv.tokenURI(1) == f"web3://{RENDERER}:1/scv/1"
    assert scv.tokenURI(12) == f"web3://{RENDERER}:1/scv/12"
    with boa.reverts("erc721: invalid token ID"):
        scv.tokenURI(13)


def test_scv_set_metadata_uri(world, scv, alice, deployer):
    buy_scvs(world, alice, 1)
    scv.set_metadata_uri(NEW_BASE, ".json", sender=deployer)
    assert event_names(scv) == ["MetadataURIUpdated", "BatchMetadataUpdate"]
    assert log_args(events(scv, "BatchMetadataUpdate")[0]) == (0, MAX_UINT256)
    assert scv.tokenURI(1) == NEW_BASE + "1.json"


def test_planets_token_uri(planets, deployer):
    planets.create_planet("Aiur", TERRAN, 3, 0, 0, 10_000, 10_000, sender=deployer)
    assert planets.tokenURI(1) == f"web3://{RENDERER}:1/planets/1"
    with boa.reverts("erc721: invalid token ID"):
        planets.tokenURI(2)
    planets.set_metadata_uri(NEW_BASE, ".json", sender=deployer)
    assert event_names(planets) == ["MetadataURIUpdated", "BatchMetadataUpdate"]
    assert log_args(events(planets, "BatchMetadataUpdate")[0]) == (0, MAX_UINT256)
    assert planets.tokenURI(1) == NEW_BASE + "1.json"


def test_spaceships_uri(spaceships, deployer):
    spaceships.create_ship_type("Viper", FIGHTER, 1, 0, 0, 1, 1, 1, 1, 1, sender=deployer)
    uri_logs = events(spaceships, "URI")
    assert [log_args(log) for log in uri_logs] == [(f"web3://{RENDERER}:1/ships/1", 1)]
    spaceships.create_ship_type("Wraith", FIGHTER, 1, 0, 0, 1, 1, 1, 1, 1, sender=deployer)
    assert spaceships.uri(1) == SHIPS_BASE + "1"
    assert spaceships.uri(2) == SHIPS_BASE + "2"
    assert "{id}" not in spaceships.uri(2)
    with boa.reverts("spaceships: unknown ship type"):
        spaceships.uri(3)
    with boa.reverts("spaceships: unknown ship type"):
        spaceships.uri(0)


def test_spaceships_set_metadata_uri_emits_uri_per_type(spaceships, deployer):
    for name in ("A", "B", "C"):
        spaceships.create_ship_type(name, FIGHTER, 1, 0, 0, 1, 1, 1, 1, 1, sender=deployer)
    spaceships.set_metadata_uri(NEW_BASE, ".json", sender=deployer)
    assert event_names(spaceships) == ["MetadataURIUpdated", "URI", "URI", "URI"]
    assert [log_args(log) for log in events(spaceships, "URI")] == [
        (NEW_BASE + "1.json", 1),
        (NEW_BASE + "2.json", 2),
        (NEW_BASE + "3.json", 3),
    ]
    assert spaceships.uri(2) == NEW_BASE + "2.json"


def test_spaceships_set_metadata_uri_without_types(spaceships, deployer):
    spaceships.set_metadata_uri(NEW_BASE, "", sender=deployer)
    assert event_names(spaceships) == ["MetadataURIUpdated"]


def test_contract_uri_values(world):
    assert world.scv.contractURI() == f"web3://{RENDERER}:1/scv/contract"
    assert world.planets.contractURI() == f"web3://{RENDERER}:1/planets/contract"
    assert world.spaceships.contractURI() == f"web3://{RENDERER}:1/ships/contract"


def test_set_contract_uri_emits_erc7572_event(world, deployer):
    new_uri = "web3://0x2222222222222222222222222222222222222222:8453/contract.json"
    for contract in (world.scv, world.planets, world.spaceships):
        contract.set_contract_uri(new_uri, sender=deployer)
        assert event_names(contract) == ["ContractURIUpdated"]
        assert contract.contractURI() == new_uri


def test_constructor_contract_uri_event(credits, deployer):
    planets = Planets.deploy(PLANETS_BASE, "", "web3://x/contract")
    assert "ContractURIUpdated" in event_names(planets)
    silent = Planets.deploy(PLANETS_BASE, "", "")
    assert "ContractURIUpdated" not in event_names(silent)
    assert silent.contractURI() == ""
    scv = SCV.deploy(credits.address, deployer, False, 1, 1, SCV_BASE, ".json", "web3://x/scv")
    assert scv.contractURI() == "web3://x/scv"
    ships = Spaceships.deploy(credits.address, credits.address, deployer, SHIPS_BASE, "", "web3://x/ships")
    assert ships.contractURI() == "web3://x/ships"


def test_max_length_uris(world, scv, alice, deployer):
    base = "web3://" + "a" * 153  # 160 characters
    suffix = "s" * 32
    scv.set_metadata_uri(base, suffix, sender=deployer)
    buy_scvs(world, alice, 1)
    assert scv.tokenURI(1) == base + "1" + suffix
    long_contract_uri = "w" * 256
    scv.set_contract_uri(long_contract_uri, sender=deployer)
    assert scv.contractURI() == long_contract_uri
