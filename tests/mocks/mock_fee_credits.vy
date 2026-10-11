# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Mock Fee-On-Transfer CREDITS
@custom:contract-name mock_fee_credits
@license MIT
@notice Test-only ERC-20 that burns `fee_bps` of every
        `transferFrom`. If `return_false` is set, `transferFrom`
        moves nothing and returns `False` instead of reverting.
"""


from snekmate.auth import ownable
initializes: ownable
from snekmate.tokens import erc20
initializes: erc20[ownable := ownable]


exports: (
    erc20.transfer,
    erc20.approve,
    erc20.balanceOf,
    erc20.allowance,
    erc20.totalSupply,
    erc20.decimals,
    erc20.mint,
)


fee_bps: public(uint256)
return_false: public(bool)


@deploy
def __init__(fee_bps_: uint256):
    ownable.__init__()
    erc20.__init__("Mock Fee Credits", "FCRED", 18, "Mock Fee Credits", "1")
    self.fee_bps = fee_bps_


@external
def set_return_false(enabled: bool):
    self.return_false = enabled


@external
def transferFrom(owner: address, to: address, amount: uint256) -> bool:
    if self.return_false:
        return False
    erc20._spend_allowance(owner, msg.sender, amount)
    fee: uint256 = amount * self.fee_bps // 10_000
    erc20._transfer(owner, to, amount - fee)
    if fee != 0:
        erc20._burn(owner, fee)
    return True
