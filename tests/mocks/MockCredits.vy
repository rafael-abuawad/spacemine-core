# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Mock CREDITS (Plain ERC-20)
@custom:contract-name MockCredits
@license MIT
@notice Test-only stand-in for the third-party CREDITS token:
        a plain snekmate `erc20` whose deployer can `mint`.
"""


from snekmate.auth import ownable
initializes: ownable
from snekmate.tokens import erc20
initializes: erc20[ownable := ownable]


exports: erc20.__interface__


@deploy
def __init__():
    ownable.__init__()
    erc20.__init__("Mock Credits", "CRED", 18, "Mock Credits", "1")
