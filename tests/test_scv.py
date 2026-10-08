import boa
import pytest
from eth_abi import encode
from eth_utils import keccak

from helpers import (
    DEAD_ADDRESS,
    E18,
    HISTORY_ADDRESS,
    HISTORY_CODE,
    KIND_GAS,
    KIND_MINERAL,
    SCV_BASE,
    SCV_PRICE,
    ZERO_ADDRESS,
    block_number,
    buy_and_reveal,
    buy_scvs,
    event_names,
    events,
    expected_roll,
    fund_credits,
    load_mock,
    log_args,
)
from src import SCV


def deploy_scv(credits, treasury, burn=False, price=SCV_PRICE, max_supply=100):
    contract = SCV.deploy(credits.address, treasury, burn, price, max_supply, SCV_BASE, "", "")
    contract.set_sale_active(True)
    return contract


# ---------------------------------------------------------------------------
# Constructor and static surface
# ---------------------------------------------------------------------------


def test_constructor_state(scv, credits, deployer, world):
    assert scv.name() == "Spacemine SCV"
    assert scv.symbol() == "SCV"
    assert scv.credits() == credits.address
    assert scv.treasury() == world.treasury
    assert scv.burn_proceeds() is False
    assert scv.price() == SCV_PRICE
    assert scv.max_supply() == 10_000
    assert scv.current_generation() == 1
    assert scv.owner() == deployer
    assert scv.mining() == world.mining.address
    assert scv.MAX_PER_TX() == 20
    assert scv.REVEAL_DELAY() == 2
    assert scv.BURN_ADDRESS() == DEAD_ADDRESS


@pytest.mark.parametrize(
    "args,message",
    [
        ((ZERO_ADDRESS, "treasury", False, SCV_PRICE, 10), "scv: credits is the zero address"),
        (("credits", ZERO_ADDRESS, False, SCV_PRICE, 10), "scv: treasury is the zero address"),
        (("credits", "treasury", False, 0, 10), "scv: zero price"),
        (("credits", "treasury", False, SCV_PRICE, 0), "scv: zero max supply"),
    ],
)
def test_constructor_reverts(credits, alice, args, message):
    resolved = [credits.address if a == "credits" else alice if a == "treasury" else a for a in args]
    with boa.reverts(message):
        SCV.deploy(*resolved, SCV_BASE, "", "")


def test_burn_mode_allows_zero_treasury(credits):
    contract = SCV.deploy(credits.address, ZERO_ADDRESS, True, SCV_PRICE, 10, SCV_BASE, "", "")
    assert contract.burn_proceeds() is True


def test_supports_interface(scv):
    for interface_id in ["01ffc9a7", "80ac58cd", "5b5e139f", "780e9d63", "589c5ce2", "49064906", "2a55205a"]:
        assert scv.supportsInterface(bytes.fromhex(interface_id))
    for interface_id in ["d9b67a26", "b45a3c0e", "ffffffff", "00000000"]:
        assert not scv.supportsInterface(bytes.fromhex(interface_id))


def test_not_exported_functions(scv):
    names = {item["name"] for item in scv.abi if item["type"] == "function"}
    for forbidden in ["safe_mint", "set_minter", "is_minter", "burn", "set_token_royalty", "set_uri"]:
        assert forbidden not in names
    for required in ["permit", "nonces", "DOMAIN_SEPARATOR", "eip712Domain", "contractURI", "tokenURI"]:
        assert required in names


# ---------------------------------------------------------------------------
# buy
# ---------------------------------------------------------------------------


def test_buy_exact_allowance(world, scv, credits, alice):
    fund_credits(world, alice, 3 * SCV_PRICE)
    treasury_before = credits.balanceOf(world.treasury)
    first = scv.buy(3, 3 * SCV_PRICE, sender=alice)
    purchased = events(scv, "Purchased")

    assert first == 1
    assert scv.balanceOf(alice) == 3
    assert [scv.ownerOf(i) for i in (1, 2, 3)] == [alice] * 3
    assert scv.total_minted() == 3
    assert scv.totalSupply() == 3
    assert credits.balanceOf(alice) == 0
    assert credits.allowance(alice, scv.address) == 0
    assert credits.balanceOf(world.treasury) - treasury_before == 3 * SCV_PRICE
    assert len(purchased) == 1
    assert (purchased[0].buyer, purchased[0].first_token_id, purchased[0].quantity) == (alice, 1, 3)
    assert purchased[0].total_cost == 3 * SCV_PRICE


def test_buy_sequential_ids_across_buyers(world, scv, alice, bob):
    assert buy_scvs(world, alice, 2) == [1, 2]
    assert buy_scvs(world, bob, 3) == [3, 4, 5]
    assert scv.tokenOfOwnerByIndex(bob, 0) == 3
    assert scv.tokenByIndex(4) == 5


def test_buy_insufficient_allowance(world, scv, credits, alice):
    fund_credits(world, alice, 2 * SCV_PRICE, approve=False)
    credits.approve(scv.address, 2 * SCV_PRICE - 1, sender=alice)
    with boa.reverts("erc20: insufficient allowance"):
        scv.buy(2, 2 * SCV_PRICE, sender=alice)


def test_buy_insufficient_balance(world, scv, credits, alice):
    fund_credits(world, alice, SCV_PRICE)
    credits.approve(scv.address, 2 * SCV_PRICE, sender=alice)
    with boa.reverts("erc20: transfer amount exceeds balance"):
        scv.buy(2, 2 * SCV_PRICE, sender=alice)


def test_buy_slippage_protection(world, scv, alice, deployer):
    fund_credits(world, alice, 10 * SCV_PRICE)
    scv.set_price(SCV_PRICE * 2, sender=deployer)
    with boa.reverts("scv: cost exceeds max"):
        scv.buy(1, SCV_PRICE, sender=alice)
    scv.buy(1, 2 * SCV_PRICE, sender=alice)


def test_buy_sale_not_active(world, scv, alice, deployer):
    fund_credits(world, alice, SCV_PRICE)
    scv.set_sale_active(False, sender=deployer)
    with boa.reverts("scv: sale not active"):
        scv.buy(1, SCV_PRICE, sender=alice)


@pytest.mark.parametrize("quantity", [0, 21])
def test_buy_invalid_quantity(world, scv, alice, quantity):
    fund_credits(world, alice, 30 * SCV_PRICE)
    with boa.reverts("scv: invalid quantity"):
        scv.buy(quantity, 30 * SCV_PRICE, sender=alice)


def test_buy_max_per_tx_boundary(world, scv, alice):
    assert len(buy_scvs(world, alice, 20)) == 20


def test_buy_supply_cap(world, credits, alice, deployer):
    contract = deploy_scv(credits, deployer, max_supply=5)
    credits.mint(alice, 10 * SCV_PRICE)
    credits.approve(contract.address, 10 * SCV_PRICE, sender=alice)
    contract.buy(4, 4 * SCV_PRICE, sender=alice)
    with boa.reverts("scv: max supply exceeded"):
        contract.buy(2, 2 * SCV_PRICE, sender=alice)
    contract.buy(1, SCV_PRICE, sender=alice)
    with boa.reverts("scv: max supply exceeded"):
        contract.buy(1, SCV_PRICE, sender=alice)


def test_buy_fee_on_transfer_credits_reverts(alice, deployer):
    fee_credits = load_mock("MockFeeCredits", 100)  # 1% fee
    contract = deploy_scv(fee_credits, deployer)
    fee_credits.mint(alice, 10 * SCV_PRICE)
    fee_credits.approve(contract.address, 10 * SCV_PRICE, sender=alice)
    with boa.reverts("scv: credits fee not supported"):
        contract.buy(1, 10 * SCV_PRICE, sender=alice)
    assert contract.total_minted() == 0


def test_buy_fee_on_transfer_with_zero_fee_succeeds(alice, deployer):
    fee_credits = load_mock("MockFeeCredits", 0)
    contract = deploy_scv(fee_credits, deployer)
    fee_credits.mint(alice, SCV_PRICE)
    fee_credits.approve(contract.address, SCV_PRICE, sender=alice)
    contract.buy(1, SCV_PRICE, sender=alice)
    assert fee_credits.balanceOf(deployer) == SCV_PRICE


def test_buy_credits_returning_false_reverts(alice, deployer):
    fee_credits = load_mock("MockFeeCredits", 0)
    fee_credits.set_return_false(True)
    contract = deploy_scv(fee_credits, deployer)
    fee_credits.mint(alice, SCV_PRICE)
    fee_credits.approve(contract.address, SCV_PRICE, sender=alice)
    with boa.reverts("scv: credits transfer failed"):
        contract.buy(1, SCV_PRICE, sender=alice)


def test_buy_no_return_credits(alice, deployer):
    no_return = load_mock("MockNoReturnCredits")
    contract = deploy_scv(no_return, deployer)
    no_return.mint(alice, 2 * SCV_PRICE)
    no_return.approve(contract.address, 2 * SCV_PRICE, sender=alice)
    contract.buy(2, 2 * SCV_PRICE, sender=alice)
    assert no_return.balanceOf(deployer) == 2 * SCV_PRICE
    assert contract.balanceOf(alice) == 2


def test_buy_burn_mode_sends_to_dead(credits, alice, deployer):
    contract = deploy_scv(credits, ZERO_ADDRESS, burn=True)
    credits.mint(alice, SCV_PRICE)
    credits.approve(contract.address, SCV_PRICE, sender=alice)
    contract.buy(1, SCV_PRICE, sender=alice)
    assert credits.balanceOf(DEAD_ADDRESS) == SCV_PRICE
    with boa.reverts("scv: proceeds are burned"):
        contract.set_treasury(alice, sender=deployer)


def test_buy_rejects_eth(world, scv, alice):
    fund_credits(world, alice, SCV_PRICE)
    boa.env.set_balance(alice, E18)
    with boa.reverts():
        scv.buy(1, SCV_PRICE, sender=alice, value=1)


def test_buy_by_contract_does_not_need_receiver_hook(world, scv, credits):
    caller = load_mock("MockCaller")
    credits.mint(caller.address, SCV_PRICE)
    caller.execute(credits.address, credits.approve.prepare_calldata(scv.address, SCV_PRICE))
    caller.execute(scv.address, scv.buy.prepare_calldata(1, SCV_PRICE))
    assert scv.ownerOf(1) == caller.address


def test_buy_stamps_generation_and_birth(world, scv, alice, deployer):
    scv.set_generation(7, sender=deployer)
    (token_id,) = buy_scvs(world, alice, 1)
    props = scv.properties(token_id)
    assert props.generation == 7
    assert props.born_at == boa.env.evm.patch.timestamp
    assert props.revealed is False
    assert props.seed == b"\x00" * 32
    assert scv.reveal_block(token_id) == block_number() + 2


# ---------------------------------------------------------------------------
# reveal
# ---------------------------------------------------------------------------


def test_reveal_before_and_at_window(world, scv, alice):
    (token_id,) = buy_scvs(world, alice, 1)
    with boa.reverts("scv: reveal too early"):
        scv.reveal([token_id])
    boa.env.time_travel(blocks=1)
    with boa.reverts("scv: reveal too early"):
        scv.reveal([token_id])
    boa.env.time_travel(blocks=1)
    assert block_number() == scv.reveal_block(token_id)
    with boa.reverts("scv: reveal too early"):
        scv.reveal([token_id])


def test_reveal_after_window(world, scv, alice, bob):
    ids = buy_scvs(world, alice, 3)
    boa.env.time_travel(blocks=3)
    scv.reveal(ids, sender=bob)  # anyone can reveal
    names = event_names(scv)
    revealed_logs = events(scv, "Revealed")
    seeds = set()
    for token_id in ids:
        props = scv.properties(token_id)
        assert props.revealed is True
        assert props.seed != b"\x00" * 32
        tier, power, mineral, gas = expected_roll(props.seed)
        assert (props.model, props.mining_power) == (tier, power)
        assert (props.mineral_efficiency_bps, props.gas_efficiency_bps) == (mineral, gas)
        seeds.add(props.seed)
    assert len(seeds) == 3
    assert names.count("Revealed") == 3
    assert names.count("MetadataUpdate") == 3
    assert all(not log.baseline for log in revealed_logs)


def test_reveal_seed_formula_with_eip2935_history(world, scv, alice):
    (token_id,) = buy_scvs(world, alice, 1)
    commit = scv.reveal_block(token_id)
    boa.env.time_travel(blocks=300)  # beyond the native 256-block window
    block_hash = keccak(b"spacemine-test-hash")
    boa.env.set_code(HISTORY_ADDRESS, HISTORY_CODE)
    boa.env.set_storage(HISTORY_ADDRESS, commit % 8191, int.from_bytes(block_hash, "big"))
    scv.reveal([token_id])
    props = scv.properties(token_id)
    expected_seed = keccak(encode(["bytes32", "uint256", "address"], [block_hash, token_id, scv.address]))
    assert props.seed == expected_seed
    assert (props.model, props.mining_power, props.mineral_efficiency_bps, props.gas_efficiency_bps) == expected_roll(
        expected_seed
    )


def test_reveal_expired_blockhash_fallback(world, scv, alice):
    ids = buy_scvs(world, alice, 2)
    boa.env.time_travel(blocks=300)
    scv.reveal(ids)
    revealed_logs = events(scv, "Revealed")
    for token_id in ids:
        props = scv.properties(token_id)
        assert props.revealed is True
        assert props.seed == b"\x00" * 32
        assert (props.model, props.mining_power) == (0, 100)
        assert (props.mineral_efficiency_bps, props.gas_efficiency_bps) == (5_000, 5_000)
        assert scv.mining_weight(token_id, KIND_MINERAL) == 50
    assert len(revealed_logs) == 2
    assert all(log.baseline for log in revealed_logs)


def test_baseline_is_worst_possible_roll():
    # Waiting out a bad roll never helps: every roll is >= baseline in every stat.
    for seed_int in [0, 1, 2**64 - 1, 2**256 - 1, 123456789 << 100]:
        tier, power, mineral, gas = expected_roll(seed_int.to_bytes(32, "big"))
        assert power >= 100 and mineral >= 5_000 and gas >= 5_000


def test_reveal_skips_already_revealed(world, scv, alice):
    ids = buy_and_reveal(world, alice, 2)
    before = [scv.properties(i) for i in ids]
    scv.reveal(ids)
    assert "Revealed" not in event_names(scv)
    assert [scv.properties(i) for i in ids] == before


def test_reveal_nonexistent_token(scv):
    with boa.reverts("erc721: invalid token ID"):
        scv.reveal([999])


def test_malicious_buyer_cannot_select_rolls(world, scv, credits):
    gambler = load_mock("MockGambler")
    credits.mint(gambler.address, 10 * SCV_PRICE)
    gambler.approve(credits.address, scv.address, 10 * SCV_PRICE)

    # The roll is unknown inside the mint transaction, so a conditional buy always reverts.
    with boa.reverts("gambler: roll unknown"):
        gambler.buy_if_good(scv.address, SCV_PRICE, 0)

    # Even trying to reveal in the same transaction fails, and properties are blank.
    first = gambler.buy_and_peek(scv.address, 1, SCV_PRICE)
    assert gambler.last_reveal_succeeded() is False
    assert gambler.last_seen_revealed() is False
    with boa.reverts("scv: not revealed"):
        scv.mining_weight(first, KIND_MINERAL)


# ---------------------------------------------------------------------------
# Views and Mining-only writes
# ---------------------------------------------------------------------------


def test_mining_weight(world, scv, alice):
    (token_id,) = buy_and_reveal(world, alice, 1)
    props = scv.properties(token_id)
    assert scv.mining_weight(token_id, KIND_MINERAL) == props.mining_power * props.mineral_efficiency_bps // 10_000
    assert scv.mining_weight(token_id, KIND_GAS) == props.mining_power * props.gas_efficiency_bps // 10_000
    with boa.reverts("scv: invalid kind"):
        scv.mining_weight(token_id, 2)


def test_mining_weight_unrevealed_or_missing(world, scv, alice):
    (token_id,) = buy_scvs(world, alice, 1)
    with boa.reverts("scv: not revealed"):
        scv.mining_weight(token_id, KIND_MINERAL)
    with boa.reverts("scv: not revealed"):
        scv.mining_weight(12345, KIND_MINERAL)
    assert scv.is_revealed(token_id) is False
    assert scv.is_revealed(12345) is False


def test_properties_nonexistent(scv):
    with boa.reverts("erc721: invalid token ID"):
        scv.properties(1)


def test_record_mined_only_mining(world, scv, alice):
    (token_id,) = buy_scvs(world, alice, 1)
    with boa.reverts("scv: caller is not mining"):
        scv.record_mined(token_id, KIND_MINERAL, 1, sender=alice)

    mining = world.mining.address
    scv.record_mined(token_id, KIND_MINERAL, 5, sender=mining)
    scv.record_mined(token_id, KIND_MINERAL, 7, sender=mining)
    scv.record_mined(token_id, KIND_GAS, 3, sender=mining)
    assert event_names(scv) == ["LifetimeStatsUpdated", "MetadataUpdate"]
    assert log_args(events(scv, "MetadataUpdate")[0]) == (token_id,)
    assert events(scv, "LifetimeStatsUpdated")[0].lifetime_total == 3
    assert scv.lifetime_minerals(token_id) == 12
    assert scv.lifetime_gas(token_id) == 3

    with boa.reverts("scv: invalid kind"):
        scv.record_mined(token_id, 2, 1, sender=mining)
    with boa.reverts("erc721: invalid token ID"):
        scv.record_mined(999, KIND_MINERAL, 1, sender=mining)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


def test_admin_functions_are_owner_only(scv, alice):
    calls = [
        lambda: scv.set_price(1, sender=alice),
        lambda: scv.set_sale_active(True, sender=alice),
        lambda: scv.set_max_supply(1, sender=alice),
        lambda: scv.set_treasury(alice, sender=alice),
        lambda: scv.set_generation(2, sender=alice),
        lambda: scv.set_mining(alice, sender=alice),
        lambda: scv.set_metadata_uri("x", "", sender=alice),
        lambda: scv.set_contract_uri("x", sender=alice),
        lambda: scv.set_default_royalty(alice, 100, sender=alice),
        lambda: scv.delete_default_royalty(sender=alice),
    ]
    for call in calls:
        with boa.reverts("ownable: caller is not the owner"):
            call()


def test_set_price(scv, deployer):
    with boa.reverts("scv: zero price"):
        scv.set_price(0, sender=deployer)
    scv.set_price(5 * E18, sender=deployer)
    assert events(scv, "PriceUpdated")[0].price == 5 * E18
    assert scv.price() == 5 * E18


def test_set_sale_active(scv, deployer):
    scv.set_sale_active(False, sender=deployer)
    assert events(scv, "SaleActiveUpdated")[0].active is False
    assert scv.sale_active() is False


def test_set_max_supply(world, scv, alice, deployer):
    buy_scvs(world, alice, 3)
    with boa.reverts("scv: max supply can only decrease"):
        scv.set_max_supply(10_001, sender=deployer)
    with boa.reverts("scv: max supply below minted"):
        scv.set_max_supply(2, sender=deployer)
    scv.set_max_supply(3, sender=deployer)
    assert events(scv, "MaxSupplyUpdated")[0].max_supply == 3
    assert scv.max_supply() == 3
    fund_credits(world, alice, SCV_PRICE)
    with boa.reverts("scv: max supply exceeded"):
        scv.buy(1, SCV_PRICE, sender=alice)


def test_set_treasury(world, scv, credits, alice, bob, deployer):
    with boa.reverts("scv: treasury is the zero address"):
        scv.set_treasury(ZERO_ADDRESS, sender=deployer)
    scv.set_treasury(bob, sender=deployer)
    assert events(scv, "TreasuryUpdated")[0].treasury == bob
    assert scv.treasury() == bob
    buy_scvs(world, alice, 1)
    assert credits.balanceOf(bob) == SCV_PRICE


def test_set_generation(scv, deployer):
    scv.set_generation(3, sender=deployer)
    assert events(scv, "GenerationUpdated")[0].generation == 3
    assert scv.current_generation() == 3


def test_set_mining_one_time(credits, alice, bob, deployer):
    contract = deploy_scv(credits, deployer)
    with boa.reverts("scv: mining is the zero address"):
        contract.set_mining(ZERO_ADDRESS, sender=deployer)
    contract.set_mining(alice, sender=deployer)
    assert events(contract, "MiningSet")[0].mining == alice
    assert contract.mining() == alice
    with boa.reverts("scv: mining already set"):
        contract.set_mining(bob, sender=deployer)


def test_royalties(scv, alice, deployer):
    assert scv.royaltyInfo(1, 10_000) == (deployer, 500)  # set by the deploy script
    scv.set_default_royalty(alice, 250, sender=deployer)
    assert scv.royaltyInfo(1, 10_000) == (alice, 250)
    scv.delete_default_royalty(sender=deployer)
    assert scv.royaltyInfo(1, 10_000) == (ZERO_ADDRESS, 0)


def test_two_step_ownership(scv, alice, deployer):
    scv.transfer_ownership(alice, sender=deployer)
    assert scv.owner() == deployer
    assert scv.pending_owner() == alice
    with boa.reverts("ownable_2step: caller is not the new owner"):
        scv.accept_ownership(sender=deployer)
    scv.accept_ownership(sender=alice)
    assert scv.owner() == alice
    scv.set_price(1, sender=alice)
    scv.renounce_ownership(sender=alice)
    assert scv.owner() == ZERO_ADDRESS


def test_holder_transfers(world, scv, alice, bob):
    (token_id,) = buy_and_reveal(world, alice, 1)
    scv.transferFrom(alice, bob, token_id, sender=alice)
    assert scv.ownerOf(token_id) == bob
    scv.approve(alice, token_id, sender=bob)
    assert scv.getApproved(token_id) == alice
    scv.safeTransferFrom(bob, alice, token_id, sender=alice)
    assert scv.ownerOf(token_id) == alice
    assert scv.properties(token_id).revealed is True  # properties follow the token
