# pragma version ~=0.4.3
"""
@title Mock Gambler (Malicious SCV Buyer)
@custom:contract-name mock_gambler
@license MIT
@notice Test-only contract that tries to keep only good SCV rolls:
        it buys, tries to reveal and read the properties inside the
        same transaction, and reverts unless the roll meets
        `min_power`. With commit-reveal, the roll is unknowable at
        mint time, so this strategy can never select outcomes.
"""


interface ISCVLike:
    def buy(quantity: uint256, max_total_cost: uint256) -> uint256: nonpayable
    def reveal(token_ids: DynArray[uint256, 50]): nonpayable
    def is_revealed(token_id: uint256) -> bool: view
    def mining_weight(token_id: uint256, kind: uint256) -> uint256: view


interface IERC20Like:
    def approve(spender: address, amount: uint256) -> bool: nonpayable


last_reveal_succeeded: public(bool)
last_seen_revealed: public(bool)


@external
def approve(token: address, spender: address, amount: uint256):
    extcall IERC20Like(token).approve(spender, amount)


@external
def buy_and_peek(scv: address, quantity: uint256, max_total_cost: uint256) -> uint256:
    first_id: uint256 = extcall ISCVLike(scv).buy(quantity, max_total_cost)
    ids: DynArray[uint256, 50] = [first_id]
    self.last_reveal_succeeded = raw_call(
        scv,
        abi_encode(ids, method_id=method_id("reveal(uint256[])")),
        revert_on_failure=False,
    )
    self.last_seen_revealed = staticcall ISCVLike(scv).is_revealed(first_id)
    return first_id


@external
def buy_if_good(scv: address, max_total_cost: uint256, min_weight: uint256) -> uint256:
    first_id: uint256 = extcall ISCVLike(scv).buy(1, max_total_cost)
    assert staticcall ISCVLike(scv).is_revealed(first_id), "gambler: roll unknown"
    assert staticcall ISCVLike(scv).mining_weight(first_id, 1) >= min_weight, "gambler: bad roll"
    return first_id
