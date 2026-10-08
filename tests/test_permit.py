"""EIP-712 permits: ERC-4494 on SCV (advertised via ERC-165) and EIP-2612 on MNRL/GAS."""

import boa
from eth_account import Account

from helpers import E18, buy_scvs


def chain_id() -> int:
    return boa.env.evm.patch.chain_id


def test_scv_erc4494_permit(world, scv, bob):
    signer = Account.create()
    (token_id,) = buy_scvs(world, signer.address, 1)
    deadline = boa.env.evm.patch.timestamp + 3_600
    assert scv.nonces(token_id) == 0
    assert scv.eip712Domain()[1:4] == ("Spacemine SCV", "1", chain_id())

    signed = Account.sign_typed_data(
        signer.key,
        {"name": "Spacemine SCV", "version": "1", "chainId": chain_id(), "verifyingContract": str(scv.address)},
        {
            "Permit": [
                {"name": "spender", "type": "address"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ]
        },
        {"spender": str(bob), "tokenId": token_id, "nonce": 0, "deadline": deadline},
    )
    r, s = signed.r.to_bytes(32, "big"), signed.s.to_bytes(32, "big")
    scv.permit(bob, token_id, deadline, signed.v, r, s, sender=bob)
    assert scv.getApproved(token_id) == bob
    assert scv.nonces(token_id) == 1
    assert len(scv.DOMAIN_SEPARATOR()) == 32

    with boa.reverts("erc721: invalid signature"):  # replay with the consumed nonce
        scv.permit(bob, token_id, deadline, signed.v, r, s, sender=bob)
    scv.transferFrom(signer.address, bob, token_id, sender=bob)
    assert scv.ownerOf(token_id) == bob


def test_resource_token_permit(world, minerals, spaceships):
    signer = Account.create()
    minerals.mint(signer.address, 10 * E18, sender=world.mining.address)
    deadline = boa.env.evm.patch.timestamp + 3_600
    signed = Account.sign_typed_data(
        signer.key,
        {
            "name": "Spacemine Minerals",
            "version": "1",
            "chainId": chain_id(),
            "verifyingContract": str(minerals.address),
        },
        {
            "Permit": [
                {"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ]
        },
        {
            "owner": signer.address,
            "spender": str(spaceships.address),
            "value": 10 * E18,
            "nonce": 0,
            "deadline": deadline,
        },
    )
    minerals.permit(
        signer.address,
        spaceships.address,
        10 * E18,
        deadline,
        signed.v,
        signed.r.to_bytes(32, "big"),
        signed.s.to_bytes(32, "big"),
    )
    assert minerals.allowance(signer.address, spaceships.address) == 10 * E18
    assert minerals.nonces(signer.address) == 1
    assert minerals.eip712Domain()[1] == "Spacemine Minerals"
    assert len(minerals.DOMAIN_SEPARATOR()) == 32
