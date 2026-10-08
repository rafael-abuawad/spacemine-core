import boa

from helpers import E18, ZERO_ADDRESS, event_names
from src import ResourceToken


def test_metadata(minerals, gas):
    assert (minerals.name(), minerals.symbol(), minerals.decimals()) == ("Spacemine Minerals", "MNRL", 18)
    assert (gas.name(), gas.symbol(), gas.decimals()) == ("Spacemine Gas", "GAS", 18)


def test_only_mining_is_minter(world, minerals, gas, deployer, alice):
    for token in (minerals, gas):
        assert token.is_minter(world.mining.address) is True
        assert token.is_minter(deployer) is False
        assert token.mining() == world.mining.address
        with boa.reverts("erc20: access is denied"):
            token.mint(alice, 1, sender=deployer)
        with boa.reverts("erc20: access is denied"):
            token.mint(alice, 1, sender=alice)


def test_constructor_revokes_deployer_minter(deployer, alice):
    token = ResourceToken.deploy("Spacemine Minerals", "MNRL")
    assert token.is_minter(deployer) is False
    with boa.reverts("erc20: access is denied"):
        token.mint(alice, 1, sender=deployer)


def test_set_mining_one_time(deployer, alice, bob):
    token = ResourceToken.deploy("Spacemine Gas", "GAS")
    with boa.reverts("ownable: caller is not the owner"):
        token.set_mining(alice, sender=alice)
    with boa.reverts("resource: mining is the zero address"):
        token.set_mining(ZERO_ADDRESS, sender=deployer)
    token.set_mining(alice, sender=deployer)
    assert event_names(token) == ["RoleMinterChanged", "MiningSet"]
    assert token.is_minter(alice) is True
    with boa.reverts("resource: mining already set"):
        token.set_mining(bob, sender=deployer)
    token.mint(bob, 5, sender=alice)
    assert token.balanceOf(bob) == 5


def test_no_minter_management_exported(minerals):
    names = {item["name"] for item in minerals.abi if item["type"] == "function"}
    assert "set_minter" not in names
    for required in ["burn", "burn_from", "permit", "transfer", "transferFrom", "approve", "eip712Domain"]:
        assert required in names


def test_ownership_transfer_does_not_grant_minter(minerals, deployer, alice, bob):
    minerals.transfer_ownership(alice, sender=deployer)
    minerals.accept_ownership(sender=alice)
    assert minerals.owner() == alice
    assert minerals.is_minter(alice) is False
    with boa.reverts("erc20: access is denied"):
        minerals.mint(bob, 1, sender=alice)


def test_transfers_and_burns(world, minerals, alice, bob):
    minerals.mint(alice, 10 * E18, sender=world.mining.address)
    minerals.transfer(bob, 3 * E18, sender=alice)
    assert minerals.balanceOf(bob) == 3 * E18
    minerals.burn(E18, sender=bob)
    assert minerals.totalSupply() == 9 * E18
    minerals.approve(bob, 2 * E18, sender=alice)
    minerals.burn_from(alice, 2 * E18, sender=bob)
    assert minerals.balanceOf(alice) == 5 * E18
    assert minerals.totalSupply() == 7 * E18
    with boa.reverts("erc20: insufficient allowance"):
        minerals.burn_from(alice, 1, sender=bob)
