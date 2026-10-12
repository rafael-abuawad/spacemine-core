# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Space Credits (Testnet Faucet CREDITS)
@custom:contract-name faucet_credits
@license MIT
@notice Testnet-only stand-in for the third-party CREDITS token:
        a snekmate `erc20` with 18 decimals and a public faucet.
        Anyone can `claim` `claim_amount` once per `claim_cooldown`
        seconds per address; the `owner` can retune or close the
        faucet (`claim_amount == 0`) and, as the minter, `mint`
        directly. The faucet is trivially farmable with fresh
        addresses, so never deploy this token on mainnet.
"""


# @dev We import and implement the `IERC20` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC20
implements: IERC20


# @dev We import and implement the `IERC20Detailed` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC20Detailed
implements: IERC20Detailed


# @dev We import and initialise the `ownable` module.
from snekmate.auth import ownable
initializes: ownable


# @dev We import and initialise the `erc20` module.
from snekmate.tokens import erc20
initializes: erc20[ownable := ownable]


# @dev We export the ERC-20 surface, burning, the role-checked
# `mint`, and erc20's ownership transfer (which moves the minter
# role along with ownership), but not `set_minter`.
exports: (
    erc20.transfer,
    erc20.approve,
    erc20.transferFrom,
    erc20.balanceOf,
    erc20.allowance,
    erc20.totalSupply,
    erc20.name,
    erc20.symbol,
    erc20.decimals,
    erc20.burn,
    erc20.burn_from,
    erc20.mint,
    erc20.is_minter,
    erc20.owner,
    erc20.transfer_ownership,
    erc20.renounce_ownership,
)


# @dev The maximum amount a single claim can mint (1M tokens).
MAX_CLAIM_AMOUNT: public(constant(uint256)) = 10**6 * 10**18


# @dev The maximum cooldown between claims (30 days).
MAX_CLAIM_COOLDOWN: public(constant(uint256)) = 30 * 86_400


# @dev Returns the amount minted per claim. 0 closes the faucet.
claim_amount: public(uint256)


# @dev Returns the seconds an address waits between claims.
claim_cooldown: public(uint256)


# @dev Returns the earliest timestamp at which an address can
# claim again (0 if it never claimed).
next_claim_at: public(HashMap[address, uint256])


# @dev Emitted on every successful claim.
event Claimed:
    account: indexed(address)
    amount: uint256
    next_claim_at: uint256


# @dev Emitted when the owner changes the faucet parameters.
event ClaimConfigured:
    amount: uint256
    cooldown: uint256


@deploy
@payable
def __init__(claim_amount_: uint256, claim_cooldown_: uint256):
    """
    @dev To omit the opcodes for checking the `msg.value`
         in the creation-time EVM bytecode, the constructor
         is declared as `payable`.
    @notice The `owner` and minter roles are assigned to
            `msg.sender`.
    @param claim_amount_ The 32-byte amount minted per claim.
    @param claim_cooldown_ The 32-byte cooldown in seconds.
    """
    ownable.__init__()
    erc20.__init__("Space Credits", "CRED", 18, "Space Credits", "1")
    self._configure(claim_amount_, claim_cooldown_)


@external
def claim():
    """
    @dev Mints `claim_amount` to `msg.sender`.
    @notice Reverts while the faucet is closed or until the
            caller's cooldown has elapsed.
    """
    amount: uint256 = self.claim_amount
    assert amount != empty(uint256), "faucet: closed"
    assert block.timestamp >= self.next_claim_at[msg.sender], "faucet: cooldown"
    next_at: uint256 = block.timestamp + self.claim_cooldown
    self.next_claim_at[msg.sender] = next_at
    erc20._mint(msg.sender, amount)
    log Claimed(account=msg.sender, amount=amount, next_claim_at=next_at)


@external
def set_claim(claim_amount_: uint256, claim_cooldown_: uint256):
    """
    @dev Changes the faucet parameters.
    @notice Only the `owner` can call this function. Existing
            cooldowns are kept; the new cooldown applies from
            each address's next claim.
    @param claim_amount_ The 32-byte amount minted per claim
           (0 closes the faucet).
    @param claim_cooldown_ The 32-byte cooldown in seconds.
    """
    ownable._check_owner()
    self._configure(claim_amount_, claim_cooldown_)


@internal
def _configure(claim_amount_: uint256, claim_cooldown_: uint256):
    assert claim_amount_ <= MAX_CLAIM_AMOUNT, "faucet: invalid amount"
    assert claim_cooldown_ <= MAX_CLAIM_COOLDOWN, "faucet: invalid cooldown"
    self.claim_amount = claim_amount_
    self.claim_cooldown = claim_cooldown_
    log ClaimConfigured(amount=claim_amount_, cooldown=claim_cooldown_)
