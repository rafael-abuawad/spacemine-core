"""Testnet faucet CREDITS: cooldown-gated public claims, owner controls, and use as the SCV payment token."""

import boa
import pytest

from helpers import E18, SCV_PRICE, events
from script.deploy import deploy
from src import faucet_credits as FaucetCredits

AMOUNT = 10_000 * E18
DAY = 86_400


@pytest.fixture
def faucet():
    return FaucetCredits.deploy(AMOUNT, DAY)


def test_metadata_and_roles(faucet, deployer):
    assert (faucet.name(), faucet.symbol(), faucet.decimals()) == ("Space Credits", "CRED", 18)
    assert faucet.owner() == deployer
    assert faucet.is_minter(deployer) is True
    assert (faucet.claim_amount(), faucet.claim_cooldown()) == (AMOUNT, DAY)


def test_claim_and_cooldown(faucet, alice, bob):
    with boa.env.prank(alice):
        faucet.claim()
    (log,) = events(faucet, "Claimed")
    now = boa.env.evm.patch.timestamp
    assert (log.account, log.amount, log.next_claim_at) == (alice, AMOUNT, now + DAY)
    assert faucet.balanceOf(alice) == AMOUNT
    assert faucet.next_claim_at(alice) == now + DAY

    # Cooldowns are per address.
    with boa.env.prank(bob):
        faucet.claim()
    assert faucet.balanceOf(bob) == AMOUNT

    boa.env.time_travel(seconds=DAY - 1)
    with boa.env.prank(alice), boa.reverts("faucet: cooldown"):
        faucet.claim()
    boa.env.time_travel(seconds=1)
    with boa.env.prank(alice):
        faucet.claim()
    assert faucet.balanceOf(alice) == 2 * AMOUNT
    assert faucet.totalSupply() == 3 * AMOUNT


def test_zero_cooldown_allows_repeat_claims(alice):
    faucet = FaucetCredits.deploy(E18, 0)
    with boa.env.prank(alice):
        faucet.claim()
        faucet.claim()
    assert faucet.balanceOf(alice) == 2 * E18


def test_owner_configures_and_closes(faucet, alice):
    with boa.env.prank(alice), boa.reverts("ownable: caller is not the owner"):
        faucet.set_claim(1, 1)

    faucet.set_claim(0, DAY)
    with boa.env.prank(alice), boa.reverts("faucet: closed"):
        faucet.claim()

    faucet.set_claim(5 * E18, 60)
    (log,) = events(faucet, "ClaimConfigured")
    assert (log.amount, log.cooldown) == (5 * E18, 60)
    with boa.env.prank(alice):
        faucet.claim()
    assert faucet.balanceOf(alice) == 5 * E18


@pytest.mark.parametrize(
    "amount, cooldown, reason",
    [
        (10**6 * E18 + 1, DAY, "faucet: invalid amount"),
        (AMOUNT, 30 * DAY + 1, "faucet: invalid cooldown"),
    ],
)
def test_bounds(faucet, amount, cooldown, reason):
    with boa.reverts(reason):
        faucet.set_claim(amount, cooldown)
    with boa.reverts(reason):
        FaucetCredits.deploy(amount, cooldown)


def test_only_minter_mints(faucet, deployer, alice):
    faucet.mint(alice, E18)
    assert faucet.balanceOf(alice) == E18
    with boa.env.prank(alice), boa.reverts("erc20: access is denied"):
        faucet.mint(alice, E18)


def test_ownership_transfer_moves_minter(faucet, deployer, alice):
    faucet.transfer_ownership(alice)
    assert faucet.owner() == alice
    assert faucet.is_minter(alice) is True
    assert faucet.is_minter(deployer) is False


def test_pays_for_scvs(faucet, alice):
    d = deploy(credits_address=str(faucet.address), seed_demo=False)
    d.scv.set_sale_active(True)
    with boa.env.prank(alice):
        faucet.claim()
        faucet.approve(d.scv.address, SCV_PRICE)
        d.scv.buy(1, SCV_PRICE)
    assert d.scv.balanceOf(alice) == 1
    assert faucet.balanceOf(d.treasury) == SCV_PRICE
