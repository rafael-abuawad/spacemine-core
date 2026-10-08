import boa
import pytest

from helpers import ZERO_ADDRESS, event_names, events, log_args
from src import Planets


def create(planets, sender, name="Aiur", biome=1, size=4, x=-10, y=25, mineral=11_000, gas=9_000):
    return planets.create_planet(name, biome, size, x, y, mineral, gas, sender=sender)


def test_constructor_state(planets, deployer, world):
    assert planets.name() == "Spacemine Planets"
    assert planets.symbol() == "PLNT"
    assert planets.owner() == deployer
    assert planets.mining() == world.mining.address
    assert planets.planet_count() == 0
    assert planets.totalSupply() == 0
    assert planets.MAX_NODES_PER_PLANET() == 16


def test_create_planet_mints_to_self(planets, deployer):
    planet_id = create(planets, deployer)
    logs = event_names(planets)
    assert planet_id == 1
    assert planets.ownerOf(1) == planets.address
    assert planets.balanceOf(planets.address) == 1
    assert planets.totalSupply() == 1
    assert planets.tokenByIndex(0) == 1
    assert planets.tokenOfOwnerByIndex(planets.address, 0) == 1
    assert logs == ["Transfer", "Locked", "PlanetCreated"]

    p = planets.planet(1)
    assert (p.name, p.biome, p.size, p.coord_x, p.coord_y) == ("Aiur", 1, 4, -10, 25)
    assert (p.mineral_richness_bps, p.gas_richness_bps) == (11_000, 9_000)
    assert p.created_at == boa.env.evm.patch.timestamp
    assert p.seed != b"\x00" * 32
    assert create(planets, deployer, name="Shakuras") == 2
    assert planets.planet(2).seed != p.seed


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"name": ""}, "planets: empty name"),
        ({"biome": 6}, "planets: invalid biome"),
        ({"size": 0}, "planets: invalid size"),
        ({"size": 11}, "planets: invalid size"),
        ({"mineral": 30_001}, "planets: invalid richness"),
        ({"gas": 30_001}, "planets: invalid richness"),
    ],
)
def test_create_planet_validation(planets, deployer, kwargs, message):
    with boa.reverts(message):
        create(planets, deployer, **kwargs)


def test_create_planet_bounds_accepted(planets, deployer):
    create(planets, deployer, biome=5, size=10, mineral=30_000, gas=0, x=-(2**31), y=2**31 - 1)
    create(planets, deployer, biome=0, size=1, mineral=0, gas=30_000)
    assert planets.planet_count() == 2


def test_create_planet_owner_only(planets, alice):
    with boa.reverts("ownable: caller is not the owner"):
        create(planets, alice)


def test_soulbound_transfer_paths_revert(planets, deployer, alice):
    planet_id = create(planets, deployer)
    for sender in (alice, planets.address, deployer):
        with boa.reverts("planets: soulbound"):
            planets.transferFrom(planets.address, alice, planet_id, sender=sender)
        with boa.reverts("planets: soulbound"):
            planets.safeTransferFrom(planets.address, alice, planet_id, sender=sender)
        with boa.reverts("planets: soulbound"):
            planets.safeTransferFrom(planets.address, alice, planet_id, b"data", sender=sender)
        with boa.reverts("planets: soulbound"):
            planets.approve(alice, planet_id, sender=sender)
        with boa.reverts("planets: soulbound"):
            planets.setApprovalForAll(alice, True, sender=sender)
    assert planets.ownerOf(planet_id) == planets.address
    assert planets.getApproved(planet_id) == ZERO_ADDRESS
    assert planets.isApprovedForAll(planets.address, alice) is False


def test_mutating_module_functions_absent(planets):
    names = {item["name"] for item in planets.abi if item["type"] == "function"}
    for forbidden in ["burn", "permit", "safe_mint", "set_minter", "is_minter", "nonces", "royaltyInfo"]:
        assert forbidden not in names


def test_locked(planets, deployer):
    planet_id = create(planets, deployer)
    assert planets.locked(planet_id) is True
    with boa.reverts("erc721: invalid token ID"):
        planets.locked(99)


def test_supports_interface(planets):
    for interface_id in ["01ffc9a7", "80ac58cd", "5b5e139f", "780e9d63", "49064906", "b45a3c0e"]:
        assert planets.supportsInterface(bytes.fromhex(interface_id))
    for interface_id in ["589c5ce2", "2a55205a", "d9b67a26", "ffffffff"]:
        assert not planets.supportsInterface(bytes.fromhex(interface_id))


def test_planet_view_reverts_for_unknown(planets):
    with boa.reverts("erc721: invalid token ID"):
        planets.planet(1)


def test_register_node_only_mining(planets, deployer, alice, world):
    planet_id = create(planets, deployer)
    with boa.reverts("planets: caller is not mining"):
        planets.register_node(planet_id, 1, sender=alice)
    planets.register_node(planet_id, 42, sender=world.mining.address)
    assert event_names(planets) == ["NodeRegistered", "MetadataUpdate"]
    assert planets.nodes_of(planet_id) == [42]
    with boa.reverts("erc721: invalid token ID"):
        planets.register_node(99, 1, sender=world.mining.address)


def test_register_node_limit(planets, deployer, world):
    planet_id = create(planets, deployer)
    for node_id in range(1, 17):
        planets.register_node(planet_id, node_id, sender=world.mining.address)
    assert len(planets.nodes_of(planet_id)) == 16
    with boa.reverts("planets: node limit reached"):
        planets.register_node(planet_id, 17, sender=world.mining.address)


def test_set_mining_one_time(deployer, alice, bob):
    contract = Planets.deploy("", "", "")
    with boa.reverts("ownable: caller is not the owner"):
        contract.set_mining(alice, sender=alice)
    with boa.reverts("planets: mining is the zero address"):
        contract.set_mining(ZERO_ADDRESS, sender=deployer)
    contract.set_mining(alice, sender=deployer)
    assert log_args(events(contract, "MiningSet")[0]) == (alice,)
    with boa.reverts("planets: mining already set"):
        contract.set_mining(bob, sender=deployer)


def test_admin_owner_only(planets, alice):
    with boa.reverts("ownable: caller is not the owner"):
        planets.set_metadata_uri("x", "", sender=alice)
    with boa.reverts("ownable: caller is not the owner"):
        planets.set_contract_uri("x", sender=alice)


def test_two_step_ownership(planets, deployer, alice):
    planets.transfer_ownership(alice, sender=deployer)
    assert planets.pending_owner() == alice
    planets.accept_ownership(sender=alice)
    assert planets.owner() == alice
    create(planets, alice)
    planets.renounce_ownership(sender=alice)
    assert planets.owner() == ZERO_ADDRESS
