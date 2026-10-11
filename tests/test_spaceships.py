import boa
import pytest

from helpers import (
    CRUISER,
    E18,
    FIGHTER,
    FREIGHTER,
    FRIGATE,
    SHIPS_BASE,
    ZERO_ADDRESS,
    event_names,
    events,
    give_resources,
    load_mock,
    log_args,
)
from src import spaceships as Spaceships


def create(spaceships, sender, name="Viper", ship_class=FIGHTER, mineral=100 * E18, gas=0, max_supply=0, stats=None):
    hull, shield, attack, speed, cargo = stats or (100, 20, 35, 90, 10)
    return spaceships.create_ship_type(
        name, ship_class, mineral, gas, max_supply, hull, shield, attack, speed, cargo, sender=sender
    )


@pytest.fixture
def ships(spaceships, deployer):
    """Mineral-only fighter (1), mixed frigate (2), gas-only cruiser (3, capped at 5)."""
    fighter = create(spaceships, deployer, "Viper", FIGHTER, 100 * E18, 0)
    frigate = create(spaceships, deployer, "Valkyrie", FRIGATE, 150 * E18, 75 * E18, 0, (300, 120, 60, 60, 200))
    cruiser = create(spaceships, deployer, "Behemoth", CRUISER, 0, 600 * E18, 5, (900, 400, 250, 25, 800))
    return fighter, frigate, cruiser


def calldata(fn, *args) -> bytes:
    return fn.prepare_calldata(*args)


# ---------------------------------------------------------------------------
# Static surface
# ---------------------------------------------------------------------------


def test_constructor_state(world, spaceships, deployer):
    assert spaceships.minerals() == world.minerals.address
    assert spaceships.gas() == world.gas.address
    assert spaceships.treasury() == world.treasury
    assert spaceships.treasury_mode() is False
    assert spaceships.ship_type_count() == 0
    assert spaceships.owner() == deployer
    assert spaceships.royaltyInfo(1, 10_000) == (world.treasury, 500)


def test_constructor_rejects_zero_tokens(world, deployer):
    with boa.reverts("spaceships: zero address"):
        Spaceships.deploy(ZERO_ADDRESS, world.gas.address, deployer, "", "", "")
    with boa.reverts("spaceships: zero address"):
        Spaceships.deploy(world.minerals.address, ZERO_ADDRESS, deployer, "", "", "")


def test_supports_interface(spaceships):
    for interface_id in ["01ffc9a7", "d9b67a26", "0e89341c", "2a55205a"]:
        assert spaceships.supportsInterface(bytes.fromhex(interface_id))
    for interface_id in ["80ac58cd", "49064906", "b45a3c0e", "ffffffff"]:
        assert not spaceships.supportsInterface(bytes.fromhex(interface_id))


def test_exported_surface(spaceships):
    names = {item["name"] for item in spaceships.abi if item["type"] == "function"}
    for forbidden in ["safe_mint", "safe_mint_batch", "set_uri", "set_minter", "is_minter", "set_token_royalty"]:
        assert forbidden not in names
    for required in [
        "safeTransferFrom",
        "safeBatchTransferFrom",
        "setApprovalForAll",
        "balanceOf",
        "balanceOfBatch",
        "isApprovedForAll",
        "exists",
        "total_supply",
        "burn",
        "burn_batch",
        "uri",
        "contractURI",
    ]:
        assert required in names


def test_no_eth_and_no_credits(spaceships, credits):
    payable = [
        item["name"] for item in spaceships.abi if item["type"] == "function" and item["stateMutability"] == "payable"
    ]
    assert payable == []
    constructor_inputs = next(item for item in spaceships.abi if item["type"] == "constructor")["inputs"]
    assert "credits" not in {i["name"].strip("_") for i in constructor_inputs}
    assert credits.address not in (spaceships.minerals(), spaceships.gas())


# ---------------------------------------------------------------------------
# Ship type management
# ---------------------------------------------------------------------------


def test_create_ship_type(spaceships, deployer):
    ship_id = create(spaceships, deployer, "Viper", FIGHTER, 100 * E18, 5 * E18, 1_000, (1, 2, 3, 4, 5))
    assert event_names(spaceships) == ["ShipTypeCreated", "URI"]
    created = events(spaceships, "ShipTypeCreated")[0]
    assert (created.ship_id, created.name, created.ship_class) == (1, "Viper", FIGHTER)
    assert log_args(events(spaceships, "URI")[0]) == (SHIPS_BASE + "1", 1)
    assert ship_id == 1
    ship = spaceships.ship_type(1)
    assert (ship.name, ship.ship_class, ship.mineral_cost, ship.gas_cost) == ("Viper", FIGHTER, 100 * E18, 5 * E18)
    assert (ship.max_supply, ship.minted, ship.active) == (1_000, 0, True)
    assert (ship.hull, ship.shield, ship.attack, ship.speed, ship.cargo) == (1, 2, 3, 4, 5)
    assert ship.created_at == boa.env.evm.patch.timestamp
    assert spaceships.ship_type_count() == 1
    assert spaceships.exists(1) is False  # snekmate `exists` tracks supply, not type registration


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"name": ""}, "spaceships: empty name"),
        ({"ship_class": 0}, "spaceships: invalid class"),  # empty flag
        ({"ship_class": FIGHTER | FREIGHTER}, "spaceships: invalid class"),  # two classes
        ({"mineral": 0, "gas": 0}, "spaceships: free ship"),
    ],
)
def test_create_ship_type_validation(spaceships, deployer, kwargs, message):
    with boa.reverts(message):
        create(spaceships, deployer, **kwargs)


def test_create_ship_type_limit(spaceships, deployer):
    for i in range(64):
        create(spaceships, deployer, f"S{i}")
    with boa.reverts("spaceships: too many ship types"):
        create(spaceships, deployer, "Overflow")


def test_admin_owner_only(spaceships, ships, alice):
    calls = [
        lambda: create(spaceships, alice),
        lambda: spaceships.set_ship_active(1, False, sender=alice),
        lambda: spaceships.set_ship_prices(1, 1, 1, sender=alice),
        lambda: spaceships.set_ship_max_supply(1, 1, sender=alice),
        lambda: spaceships.set_treasury(alice, sender=alice),
        lambda: spaceships.set_treasury_mode(True, sender=alice),
        lambda: spaceships.set_metadata_uri("", "", sender=alice),
        lambda: spaceships.set_contract_uri("", sender=alice),
        lambda: spaceships.set_default_royalty(alice, 1, sender=alice),
        lambda: spaceships.delete_default_royalty(sender=alice),
    ]
    for call in calls:
        with boa.reverts("ownable: caller is not the owner"):
            call()


def test_setters_unknown_ship(spaceships, deployer):
    for call in (
        lambda: spaceships.set_ship_active(1, False, sender=deployer),
        lambda: spaceships.set_ship_prices(1, 1, 1, sender=deployer),
        lambda: spaceships.set_ship_max_supply(1, 1, sender=deployer),
        lambda: spaceships.ship_type(1),
        lambda: spaceships.quote(1, 1),
    ):
        with boa.reverts("spaceships: unknown ship type"):
            call()


def test_set_ship_active_and_prices(spaceships, ships, deployer):
    fighter = ships[0]
    spaceships.set_ship_active(fighter, False, sender=deployer)
    assert [(log.ship_id, log.active) for log in events(spaceships, "ShipActiveUpdated")] == [(fighter, False)]
    spaceships.set_ship_prices(fighter, 1, 2, sender=deployer)
    assert [(log.mineral_cost, log.gas_cost) for log in events(spaceships, "ShipPricesUpdated")] == [(1, 2)]
    with boa.reverts("spaceships: free ship"):
        spaceships.set_ship_prices(fighter, 0, 0, sender=deployer)
    ship = spaceships.ship_type(fighter)
    assert (ship.active, ship.mineral_cost, ship.gas_cost) == (False, 1, 2)


def test_set_ship_max_supply(world, spaceships, ships, deployer, alice):
    fighter, _, cruiser = ships
    give_resources(world, alice, minerals=1_000 * E18)
    spaceships.buy(fighter, 3, 300 * E18, 0, sender=alice)

    with boa.reverts("spaceships: max supply can only decrease"):
        spaceships.set_ship_max_supply(fighter, 0, sender=deployer)
    with boa.reverts("spaceships: max supply below minted"):
        spaceships.set_ship_max_supply(fighter, 2, sender=deployer)
    spaceships.set_ship_max_supply(fighter, 10, sender=deployer)  # unlimited -> 10 is a decrease
    assert [(log.ship_id, log.max_supply) for log in events(spaceships, "ShipMaxSupplyUpdated")] == [(fighter, 10)]
    with boa.reverts("spaceships: max supply can only decrease"):
        spaceships.set_ship_max_supply(fighter, 11, sender=deployer)
    spaceships.set_ship_max_supply(fighter, 3, sender=deployer)
    assert spaceships.ship_type(fighter).max_supply == 3
    with boa.reverts("spaceships: max supply can only decrease"):
        spaceships.set_ship_max_supply(cruiser, 6, sender=deployer)


def test_stats_immutable_after_creation(world, spaceships, ships, deployer, alice):
    _, frigate, _ = ships
    before = spaceships.ship_type(frigate)
    spaceships.set_ship_prices(frigate, 1, 1, sender=deployer)
    spaceships.set_ship_active(frigate, False, sender=deployer)
    spaceships.set_ship_active(frigate, True, sender=deployer)
    spaceships.set_ship_max_supply(frigate, 100, sender=deployer)
    give_resources(world, alice, minerals=10, gas=10)
    spaceships.buy(frigate, 2, 2, 2, sender=alice)
    after = spaceships.ship_type(frigate)
    stat_fields = ("name", "ship_class", "hull", "shield", "attack", "speed", "cargo", "created_at")
    assert [getattr(after, f) for f in stat_fields] == [getattr(before, f) for f in stat_fields]
    setters = {
        item["name"] for item in spaceships.abi if item["type"] == "function" and item["name"].startswith("set_")
    }
    assert setters == {
        "set_ship_active",
        "set_ship_prices",
        "set_ship_max_supply",
        "set_treasury",
        "set_treasury_mode",
        "set_metadata_uri",
        "set_contract_uri",
        "set_default_royalty",
    }


def test_treasury_setters(world, minerals, gas, deployer, alice):
    contract = Spaceships.deploy(minerals.address, gas.address, ZERO_ADDRESS, SHIPS_BASE, "", "")
    with boa.reverts("spaceships: treasury is the zero address"):
        contract.set_treasury_mode(True, sender=deployer)
    with boa.reverts("spaceships: treasury is the zero address"):
        contract.set_treasury(ZERO_ADDRESS, sender=deployer)
    contract.set_treasury(alice, sender=deployer)
    assert log_args(events(contract, "TreasuryUpdated")[0]) == (alice,)
    contract.set_treasury_mode(True, sender=deployer)
    assert log_args(events(contract, "TreasuryModeUpdated")[0]) == (True,)
    contract.set_treasury_mode(False, sender=deployer)
    assert contract.treasury_mode() is False


# ---------------------------------------------------------------------------
# buy
# ---------------------------------------------------------------------------


def test_buy_mineral_only_burns(world, spaceships, minerals, gas, ships, alice):
    fighter = ships[0]
    give_resources(world, alice, minerals=500 * E18)
    supply_before = minerals.totalSupply()
    spaceships.buy(fighter, 3, 300 * E18, 0, sender=alice)
    purchased = events(spaceships, "ShipsPurchased")
    assert [(p.buyer, p.ship_id, p.amount, p.mineral_paid, p.gas_paid) for p in purchased] == [
        (alice, fighter, 3, 300 * E18, 0)
    ]
    assert spaceships.balanceOf(alice, fighter) == 3
    assert spaceships.total_supply(fighter) == 3
    assert spaceships.exists(fighter) is True
    assert spaceships.ship_type(fighter).minted == 3
    assert minerals.balanceOf(alice) == 200 * E18
    assert minerals.totalSupply() == supply_before - 300 * E18
    assert gas.totalSupply() == 0


def test_buy_gas_only(world, spaceships, minerals, gas, ships, alice):
    cruiser = ships[2]
    give_resources(world, alice, gas=1_200 * E18)  # no MNRL approval needed
    spaceships.buy(cruiser, 2, 0, 1_200 * E18, sender=alice)
    assert spaceships.balanceOf(alice, cruiser) == 2
    assert gas.balanceOf(alice) == 0
    assert gas.totalSupply() == 0
    assert minerals.totalSupply() == 0


def test_buy_mixed(world, spaceships, minerals, gas, ships, alice):
    frigate = ships[1]
    give_resources(world, alice, minerals=300 * E18, gas=150 * E18)
    assert spaceships.quote(frigate, 2) == (300 * E18, 150 * E18)
    spaceships.buy(frigate, 2, 300 * E18, 150 * E18, sender=alice)
    assert spaceships.balanceOf(alice, frigate) == 2
    assert minerals.totalSupply() == 0
    assert gas.totalSupply() == 0


def test_buy_insufficient_balance_or_allowance(world, spaceships, minerals, gas, ships, alice):
    frigate = ships[1]
    give_resources(world, alice, minerals=150 * E18, gas=75 * E18, approve=False)

    with boa.reverts("erc20: insufficient allowance"):
        spaceships.buy(frigate, 1, 150 * E18, 75 * E18, sender=alice)
    minerals.approve(spaceships.address, 150 * E18, sender=alice)
    with boa.reverts("erc20: insufficient allowance"):  # GAS allowance missing
        spaceships.buy(frigate, 1, 150 * E18, 75 * E18, sender=alice)
    gas.approve(spaceships.address, 10**30, sender=alice)

    minerals.approve(spaceships.address, 10**30, sender=alice)
    with boa.reverts("erc20: burn amount exceeds balance"):  # MNRL balance too low
        spaceships.buy(frigate, 2, 300 * E18, 150 * E18, sender=alice)
    minerals.mint(alice, 150 * E18, sender=world.mining.address)
    with boa.reverts("erc20: burn amount exceeds balance"):  # GAS balance too low
        spaceships.buy(frigate, 2, 300 * E18, 150 * E18, sender=alice)
    spaceships.buy(frigate, 1, 150 * E18, 75 * E18, sender=alice)


def test_buy_slippage(world, spaceships, ships, deployer, alice):
    frigate = ships[1]
    give_resources(world, alice, minerals=10**24, gas=10**24)
    with boa.reverts("spaceships: mineral cost exceeds max"):
        spaceships.buy(frigate, 2, 300 * E18 - 1, 150 * E18, sender=alice)
    with boa.reverts("spaceships: gas cost exceeds max"):
        spaceships.buy(frigate, 2, 300 * E18, 150 * E18 - 1, sender=alice)
    spaceships.set_ship_prices(frigate, 200 * E18, 75 * E18, sender=deployer)
    with boa.reverts("spaceships: mineral cost exceeds max"):
        spaceships.buy(frigate, 1, 150 * E18, 75 * E18, sender=alice)


def test_buy_supply_cap_and_inactive(world, spaceships, ships, deployer, alice):
    _, _, cruiser = ships
    give_resources(world, alice, gas=10**24)
    spaceships.buy(cruiser, 4, 0, 10**24, sender=alice)
    with boa.reverts("spaceships: max supply exceeded"):
        spaceships.buy(cruiser, 2, 0, 10**24, sender=alice)
    spaceships.buy(cruiser, 1, 0, 10**24, sender=alice)
    with boa.reverts("spaceships: max supply exceeded"):
        spaceships.buy(cruiser, 1, 0, 10**24, sender=alice)
    spaceships.burn(alice, cruiser, 5, sender=alice)  # burning does not free capped supply
    with boa.reverts("spaceships: max supply exceeded"):
        spaceships.buy(cruiser, 1, 0, 10**24, sender=alice)

    spaceships.set_ship_active(ships[0], False, sender=deployer)
    with boa.reverts("spaceships: ship type inactive"):
        spaceships.buy(ships[0], 1, 10**24, 0, sender=alice)


@pytest.mark.parametrize("amount", [0, 51])
def test_buy_invalid_amount(world, spaceships, ships, alice, amount):
    give_resources(world, alice, minerals=10**24)
    with boa.reverts("spaceships: invalid amount"):
        spaceships.buy(ships[0], amount, 10**24, 0, sender=alice)


def test_buy_unknown_ship(world, spaceships, ships, alice):
    with boa.reverts("spaceships: unknown ship type"):
        spaceships.buy(4, 1, 10**24, 10**24, sender=alice)
    with boa.reverts("spaceships: unknown ship type"):
        spaceships.buy(0, 1, 10**24, 10**24, sender=alice)


def test_buy_rejects_eth(world, spaceships, ships, alice):
    give_resources(world, alice, minerals=100 * E18)
    boa.env.set_balance(alice, E18)
    with boa.reverts():
        spaceships.buy(ships[0], 1, 100 * E18, 0, sender=alice, value=1)


def test_buy_treasury_mode(world, spaceships, minerals, gas, ships, deployer, alice, bob):
    frigate = ships[1]
    spaceships.set_treasury(bob, sender=deployer)
    spaceships.set_treasury_mode(True, sender=deployer)
    give_resources(world, alice, minerals=150 * E18, gas=75 * E18)
    spaceships.buy(frigate, 1, 150 * E18, 75 * E18, sender=alice)
    assert minerals.balanceOf(bob) == 150 * E18
    assert gas.balanceOf(bob) == 75 * E18
    assert minerals.totalSupply() == 150 * E18  # moved, not burned
    assert gas.totalSupply() == 75 * E18


# ---------------------------------------------------------------------------
# buy_batch
# ---------------------------------------------------------------------------


def test_buy_batch_aggregates(world, spaceships, minerals, gas, ships, alice):
    fighter, frigate, cruiser = ships
    mineral_total = 2 * 100 * E18 + 1 * 150 * E18 + 1 * 100 * E18
    gas_total = 1 * 75 * E18 + 1 * 600 * E18
    give_resources(world, alice, minerals=mineral_total, gas=gas_total)
    spaceships.buy_batch([fighter, frigate, cruiser, fighter], [2, 1, 1, 1], mineral_total, gas_total, sender=alice)
    assert spaceships.balanceOfBatch([alice] * 3, [fighter, frigate, cruiser]) == [3, 1, 1]
    assert minerals.balanceOf(alice) == 0
    assert gas.balanceOf(alice) == 0
    assert minerals.totalSupply() == gas.totalSupply() == 0


def test_buy_batch_single_payment_per_resource(world, spaceships, ships, alice):
    fighter, frigate, _ = ships
    give_resources(world, alice, minerals=10**24, gas=10**24)
    spaceships.buy_batch([fighter, frigate, fighter], [1, 1, 2], 10**24, 10**24, sender=alice)
    logs = spaceships.get_logs()
    names = [type(log).__name__ for log in logs]
    assert names.count("ShipsPurchased") == 3
    assert names.count("TransferBatch") == 1
    burns = [log for log in logs if type(log).__name__ == "Transfer" and log.receiver == ZERO_ADDRESS]
    assert sorted((str(log.address), log.value) for log in burns) == sorted(
        [(str(world.minerals.address), 450 * E18), (str(world.gas.address), 75 * E18)]
    )


def test_buy_batch_validation(world, spaceships, ships, alice):
    fighter, frigate, cruiser = ships
    give_resources(world, alice, minerals=10**24, gas=10**24)
    with boa.reverts("spaceships: length mismatch"):
        spaceships.buy_batch([fighter], [1, 2], 10**24, 10**24, sender=alice)
    with boa.reverts("spaceships: empty batch"):
        spaceships.buy_batch([], [], 10**24, 10**24, sender=alice)
    with boa.reverts("spaceships: mineral cost exceeds max"):
        spaceships.buy_batch([fighter, frigate], [1, 1], 250 * E18 - 1, 10**24, sender=alice)
    with boa.reverts("spaceships: gas cost exceeds max"):
        spaceships.buy_batch([frigate, cruiser], [1, 1], 10**24, 675 * E18 - 1, sender=alice)
    with boa.reverts("spaceships: max supply exceeded"):  # duplicates are checked cumulatively
        spaceships.buy_batch([cruiser, cruiser], [3, 3], 10**24, 10**24, sender=alice)
    with boa.reverts("spaceships: invalid amount"):
        spaceships.buy_batch([fighter], [0], 10**24, 10**24, sender=alice)


# ---------------------------------------------------------------------------
# Receivers and reentrancy
# ---------------------------------------------------------------------------


def fund_contract(world, contract, minerals=10**24, gas=10**24):
    world.minerals.mint(contract.address, minerals, sender=world.mining.address)
    world.gas.mint(contract.address, gas, sender=world.mining.address)
    for token in (world.minerals, world.gas):
        contract.execute(token.address, calldata(token.approve, world.spaceships.address, 2**256 - 1))


def test_reentrant_receiver_cannot_double_mint(world, spaceships, ships):
    fighter = ships[0]
    receiver = load_mock("mock_receiver")
    fund_contract(world, receiver)
    receiver.set_mode(2)
    receiver.set_reentry(spaceships.address, calldata(spaceships.buy, fighter, 1, 10**24, 0))

    supply_before = world.minerals.totalSupply()
    receiver.execute(spaceships.address, calldata(spaceships.buy, fighter, 1, 10**24, 0))

    assert receiver.reentry_attempts() == 1
    assert receiver.reentry_succeeded() is False
    assert spaceships.balanceOf(receiver.address, fighter) == 1
    assert spaceships.ship_type(fighter).minted == 1
    assert world.minerals.totalSupply() == supply_before - 100 * E18  # paid exactly once


def test_reentrant_batch_receiver_cannot_double_mint(world, spaceships, ships):
    fighter, frigate, _ = ships
    receiver = load_mock("mock_receiver")
    fund_contract(world, receiver)
    receiver.set_mode(2)
    receiver.set_reentry(spaceships.address, calldata(spaceships.buy_batch, [fighter], [1], 10**24, 10**24))

    mineral_before, gas_before = world.minerals.totalSupply(), world.gas.totalSupply()
    receiver.execute(spaceships.address, calldata(spaceships.buy_batch, [fighter, frigate], [1, 1], 10**24, 10**24))

    assert receiver.reentry_attempts() == 1
    assert receiver.reentry_succeeded() is False
    assert spaceships.balanceOfBatch([receiver.address] * 2, [fighter, frigate]) == [1, 1]
    assert world.minerals.totalSupply() == mineral_before - 250 * E18
    assert world.gas.totalSupply() == gas_before - 75 * E18


def test_reentry_into_admin_paths_blocked(world, spaceships, ships, deployer):
    # Even if the owner were a hostile receiver, the hook cannot reach nonreentrant setters.
    receiver = load_mock("mock_receiver")
    fund_contract(world, receiver)
    receiver.set_mode(2)
    receiver.set_reentry(spaceships.address, calldata(spaceships.set_ship_prices, ships[0], 1, 0))
    receiver.execute(spaceships.address, calldata(spaceships.buy, ships[0], 1, 10**24, 0))
    assert receiver.reentry_succeeded() is False
    assert spaceships.ship_type(ships[0]).mineral_cost == 100 * E18


def test_accepting_receiver_can_buy(world, spaceships, ships):
    receiver = load_mock("mock_receiver")
    fund_contract(world, receiver)
    receiver.execute(spaceships.address, calldata(spaceships.buy, ships[0], 2, 10**24, 0))
    assert spaceships.balanceOf(receiver.address, ships[0]) == 2
    assert receiver.received_count() == 1


def test_rejecting_receivers_cannot_buy(world, spaceships, ships):
    receiver = load_mock("mock_receiver")
    fund_contract(world, receiver)
    receiver.set_mode(1)
    with boa.reverts("receiver: rejected"):
        receiver.execute(spaceships.address, calldata(spaceships.buy, ships[0], 1, 10**24, 0))
    receiver.set_mode(3)
    with boa.reverts("erc1155: transfer to non-IERC1155Receiver implementer"):
        receiver.execute(spaceships.address, calldata(spaceships.buy, ships[0], 1, 10**24, 0))
    with boa.reverts("erc1155: transfer to non-IERC1155Receiver implementer"):
        receiver.execute(spaceships.address, calldata(spaceships.buy_batch, [ships[0]], [1], 10**24, 0))


def test_non_receiver_contract_cannot_buy(world, spaceships, ships):
    caller = load_mock("mock_caller")
    fund_contract(world, caller)
    with boa.reverts():
        caller.execute(spaceships.address, calldata(spaceships.buy, ships[0], 1, 10**24, 0))
    assert spaceships.ship_type(ships[0]).minted == 0


# ---------------------------------------------------------------------------
# Holder operations
# ---------------------------------------------------------------------------


def test_holders_transfer_approve_burn(world, spaceships, ships, alice, bob):
    fighter, frigate, _ = ships
    give_resources(world, alice, minerals=10**24, gas=10**24)
    spaceships.buy_batch([fighter, frigate], [5, 3], 10**24, 10**24, sender=alice)

    spaceships.safeTransferFrom(alice, bob, fighter, 2, b"", sender=alice)
    assert spaceships.balanceOf(bob, fighter) == 2
    spaceships.setApprovalForAll(bob, True, sender=alice)
    assert spaceships.isApprovedForAll(alice, bob) is True
    spaceships.safeBatchTransferFrom(alice, bob, [fighter, frigate], [1, 1], b"", sender=bob)
    assert spaceships.balanceOfBatch([alice, alice, bob, bob], [fighter, frigate, fighter, frigate]) == [2, 2, 3, 1]

    spaceships.burn(bob, fighter, 1, sender=bob)
    spaceships.burn_batch(alice, [fighter, frigate], [2, 2], sender=bob)  # approved operator
    assert spaceships.total_supply(fighter) == 2
    assert spaceships.total_supply(frigate) == 1
    assert spaceships.ship_type(fighter).minted == 5  # minted counter is not reduced by burns
