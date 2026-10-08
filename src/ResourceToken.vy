# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Spacemine Resource Token (MNRL / GAS)
@custom:contract-name ResourceToken
@license MIT
@notice snekmate `erc20` with 18 decimals, deployed twice as
        `Spacemine Minerals`/`MNRL` and `Spacemine Gas`/`GAS`.
        Only the `Mining` contract can mint. The deployer's
        minter role (granted by snekmate's `erc20.__init__`) is
        revoked in the constructor. `set_mining` grants the role
        to `Mining` exactly once, and since snekmate's `set_minter`
        is not exported, nobody can ever add or remove a minter
        afterwards. This makes it impossible for an admin to mint
        resources, and impossible to brick `Mining` payouts.
        `burn` and `burn_from` are exported: `Spaceships` consumes
        resources via `burn_from`, which spends the buyer's allowance.
"""


# @dev We import and implement the `IERC20` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC20
implements: IERC20


# @dev We import and implement the `IERC20Detailed` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC20Detailed
implements: IERC20Detailed


# @dev We import and implement the `IERC20Permit`
# interface, which is written using standard Vyper
# syntax.
from snekmate.tokens.interfaces import IERC20Permit
implements: IERC20Permit


# @dev We import and implement the `IERC5267` interface,
# which is written using standard Vyper syntax.
from snekmate.utils.interfaces import IERC5267
implements: IERC5267


# @dev We import and implement the project-specific
# `IResourceToken` interface.
from .interfaces import IResourceToken
implements: IResourceToken


# @dev We import and initialise the `ownable` module and
# use the two-step ownership transfer of `ownable_2step`.
# @notice The `erc20` module's `transfer_ownership` and
# `renounce_ownership` are not exported, because they would
# hand the minter role to the new owner.
from snekmate.auth import ownable
initializes: ownable
from snekmate.auth import ownable_2step
initializes: ownable_2step[ownable := ownable]


# @dev We import and initialise the `erc20` module.
from snekmate.tokens import erc20
initializes: erc20[ownable := ownable]


# @dev We export the full ERC-20 surface, burning, permit,
# and the role-checked `mint`, but not `set_minter`.
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
    erc20.permit,
    erc20.nonces,
    erc20.DOMAIN_SEPARATOR,
    erc20.eip712_domain_separator.eip712Domain,
    ownable.owner,
    ownable_2step.pending_owner,
    ownable_2step.transfer_ownership,
    ownable_2step.accept_ownership,
    ownable_2step.renounce_ownership,
)


# @dev Returns the `Mining` contract (the only minter).
mining: public(address)


# @dev Emitted once, when the `Mining` contract is wired.
event MiningSet:
    mining: indexed(address)


@deploy
@payable
def __init__(name_: String[25], symbol_: String[5]):
    """
    @dev To omit the opcodes for checking the `msg.value`
         in the creation-time EVM bytecode, the constructor
         is declared as `payable`.
    @notice The `owner` role is assigned to `msg.sender`, but
            the minter role is revoked immediately.
    @param name_ The maximum 25-character user-readable
           string name of the token.
    @param symbol_ The maximum 5-character user-readable
           string symbol of the token.
    """
    ownable.__init__()
    ownable_2step.__init__()
    erc20.__init__(name_, symbol_, 18, name_, "1")

    erc20.is_minter[msg.sender] = False
    log erc20.RoleMinterChanged(minter=msg.sender, status=False)


@external
def set_mining(mining_: address):
    """
    @dev Grants the minter role to `Mining`, permanently.
    @notice Only the `owner` can call this function, and only once.
            After this call the `owner` has no remaining powers
            over the token besides transferring ownership.
    @param mining_ The 20-byte `Mining` address.
    """
    ownable._check_owner()
    assert self.mining == empty(address), "resource: mining already set"
    assert mining_ != empty(address), "resource: mining is the zero address"
    self.mining = mining_
    erc20.is_minter[mining_] = True
    log erc20.RoleMinterChanged(minter=mining_, status=True)
    log MiningSet(mining=mining_)
