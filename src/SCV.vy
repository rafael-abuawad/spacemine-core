# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Spacemine SCV (Mining Bot) Collection
@custom:contract-name SCV
@license MIT
@notice ERC-721 mining bots sold for CREDITS. Every SCV carries
        token-specific on-chain properties that are assigned
        through a commit-reveal scheme:
        1. `buy` mints the SCV and commits to the block hash of
           `block.number + REVEAL_DELAY` (unknown at mint time),
        2. once that block has been mined, anyone can call `reveal`,
           which derives `seed = keccak256(blockhash, token_id, self)`
           and rolls the properties from the seed.
        A buyer contract can therefore not inspect its roll inside
        the minting transaction and revert on bad outcomes.
        If the committed block hash is no longer retrievable (i.e.
        older than 256 blocks, or 8,191 blocks with EIP-2935), the
        SCV receives fixed baseline stats equal to the *worst*
        possible Standard roll, so waiting out a bad roll never pays.
        The collection uses snekmate's `erc721` module for the token
        logic, with the following deliberate omissions: `safe_mint`,
        `set_minter`, and `is_minter` are not exported (purchase is
        the only way to mint), `burn` is not exported (properties and
        lifetime stats stay attached to a live token), and `tokenURI`
        is replaced by a mutable `web3://` scheme (see `modules/metadata`).
"""


# @dev We import and implement the `IERC165` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC165
implements: IERC165


# @dev We import and implement the `IERC721` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC721
implements: IERC721


# @dev We import the `IERC20` interface, which is a
# built-in interface of the Vyper compiler, to pull
# CREDITS from buyers.
from ethereum.ercs import IERC20


# @dev We import and implement the snekmate interfaces
# for the ERC-721 extensions that this contract exposes.
from snekmate.tokens.interfaces import IERC721Metadata
implements: IERC721Metadata
from snekmate.tokens.interfaces import IERC721Enumerable
implements: IERC721Enumerable
from snekmate.tokens.interfaces import IERC721Permit
implements: IERC721Permit
from snekmate.tokens.interfaces import IERC4906
implements: IERC4906
from snekmate.extensions.interfaces import IERC2981
implements: IERC2981
from snekmate.utils.interfaces import IERC5267
implements: IERC5267


# @dev We import and implement the project-specific
# `ISCV` interface (which also defines `SCVProperties`).
from .interfaces import ISCV
implements: ISCV


# @dev We import and initialise the `ownable` module and
# use the two-step ownership transfer of `ownable_2step`.
# @notice The `erc721` module's own `transfer_ownership` and
# `renounce_ownership` are not exported: they exist to move
# the `is_minter` role, which this contract never uses.
from snekmate.auth import ownable
initializes: ownable
from snekmate.auth import ownable_2step
initializes: ownable_2step[ownable := ownable]


# @dev We import and initialise the `erc721` module.
from snekmate.tokens import erc721
initializes: erc721[ownable := ownable]


# @dev We import and initialise the `erc2981` module.
from snekmate.extensions import erc2981
initializes: erc2981[ownable := ownable]


# @dev We import the stateless `block_hash` module to read
# block hashes beyond 256 blocks where EIP-2935 is live.
from snekmate.utils import block_hash


# @dev We import and initialise the shared metadata module.
from .modules import metadata
initializes: metadata


# @dev We export (i.e. the runtime bytecode exposes these
# functions externally, allowing them to be called using
# the ABI encoding specification) an explicit subset of
# the module functions. See the contract `@notice` for the
# deliberate omissions.
exports: (
    erc721.balanceOf,
    erc721.ownerOf,
    erc721.approve,
    erc721.getApproved,
    erc721.setApprovalForAll,
    erc721.isApprovedForAll,
    erc721.transferFrom,
    erc721.safeTransferFrom,
    erc721.name,
    erc721.symbol,
    erc721.totalSupply,
    erc721.tokenByIndex,
    erc721.tokenOfOwnerByIndex,
    erc721.permit,
    erc721.nonces,
    erc721.DOMAIN_SEPARATOR,
    erc721.eip712_domain_separator.eip712Domain,
    ownable.owner,
    ownable_2step.pending_owner,
    ownable_2step.transfer_ownership,
    ownable_2step.accept_ownership,
    ownable_2step.renounce_ownership,
    erc2981.royaltyInfo,
    erc2981.set_default_royalty,
    erc2981.delete_default_royalty,
    metadata.metadata_base,
    metadata.metadata_suffix,
    metadata.contractURI,
)


# @dev Stores the ERC-165 interface identifiers of exactly
# the exported surface.
_SUPPORTED_INTERFACES: constant(bytes4[7]) = [
    0x01FFC9A7, # The ERC-165 identifier for ERC-165.
    0x80AC58CD, # The ERC-165 identifier for ERC-721.
    0x5B5E139F, # The ERC-165 identifier for the ERC-721 metadata extension.
    0x780E9D63, # The ERC-165 identifier for the ERC-721 enumeration extension.
    0x589C5CE2, # The ERC-165 identifier for ERC-4494.
    0x49064906, # The ERC-165 identifier for ERC-4906.
    0x2A55205A, # The ERC-165 identifier for ERC-2981.
]


# @dev The maximum number of SCVs that can be bought in one transaction.
MAX_PER_TX: public(constant(uint256)) = 20


# @dev The number of blocks between minting and the committed reveal block.
REVEAL_DELAY: public(constant(uint256)) = 2


# @dev The maximum number of SCVs that can be revealed in one call.
MAX_REVEAL_BATCH: public(constant(uint256)) = 50


# @dev The sink used for CREDITS when `burn_proceeds` is enabled.
BURN_ADDRESS: public(constant(address)) = 0x000000000000000000000000000000000000dEaD


# @dev Resource kinds (must match `Mining`).
KIND_MINERAL: constant(uint8) = 0
KIND_GAS: constant(uint8) = 1


# @dev The basis-point denominator.
_BPS: constant(uint256) = 10_000


# @dev Rarity tiers: 0 = Standard, 1 = Advanced, 2 = Elite, 3 = Prototype.
# The cumulative roll thresholds out of 10,000 give the probabilities
# 60% / 25% / 12% / 3%.
_TIER_THRESHOLDS: constant(uint256[4]) = [6_000, 8_500, 9_700, 10_000]


# @dev The inclusive `mining_power` range for each tier.
_TIER_POWER_MIN: constant(uint256[4]) = [100, 150, 220, 300]
_TIER_POWER_MAX: constant(uint256[4]) = [149, 219, 299, 400]


# @dev The inclusive efficiency range (in basis points) for both kinds.
MIN_EFFICIENCY_BPS: public(constant(uint16)) = 5_000
MAX_EFFICIENCY_BPS: public(constant(uint16)) = 15_000


# @dev The baseline stats assigned if the reveal block hash expired.
# They equal the worst possible Standard roll.
BASELINE_POWER: public(constant(uint16)) = 100
BASELINE_EFFICIENCY_BPS: public(constant(uint16)) = 5_000


# @dev Returns the CREDITS token address.
credits: public(immutable(IERC20))


# @dev Returns whether CREDITS proceeds are sent to `BURN_ADDRESS`
# instead of `treasury`.
burn_proceeds: public(immutable(bool))


# @dev Returns the treasury that receives CREDITS (if not burning).
treasury: public(address)


# @dev Returns the price of one SCV in CREDITS (in token base units).
price: public(uint256)


# @dev Returns the maximum number of SCVs that can ever be minted.
max_supply: public(uint256)


# @dev Returns the number of SCVs minted so far (IDs are 1-based
# and sequential, so this is also the highest token ID).
total_minted: public(uint256)


# @dev Returns whether the sale is open.
sale_active: public(bool)


# @dev Returns the generation stamped on newly minted SCVs.
current_generation: public(uint16)


# @dev Returns the `Mining` contract allowed to write lifetime stats.
mining: public(address)


# @dev Returns the committed reveal block of each SCV.
reveal_block: public(HashMap[uint256, uint256])


# @dev Returns the lifetime minerals mined by each SCV.
lifetime_minerals: public(HashMap[uint256, uint256])


# @dev Returns the lifetime gas mined by each SCV.
lifetime_gas: public(HashMap[uint256, uint256])


# @dev Mapping from token ID to its properties.
_properties: HashMap[uint256, ISCV.SCVProperties]


# @dev Emitted when SCVs are bought.
event Purchased:
    buyer: indexed(address)
    first_token_id: uint256
    quantity: uint256
    total_cost: uint256


# @dev Emitted when an SCV's properties are revealed.
event Revealed:
    token_id: indexed(uint256)
    seed: bytes32
    model: uint8
    mining_power: uint16
    mineral_efficiency_bps: uint16
    gas_efficiency_bps: uint16
    baseline: bool


# @dev Emitted when the lifetime stats of an SCV change.
event LifetimeStatsUpdated:
    token_id: indexed(uint256)
    kind: uint8
    amount: uint256
    lifetime_total: uint256


# @dev Emitted when the price changes.
event PriceUpdated:
    price: uint256


# @dev Emitted when the sale is opened or closed.
event SaleActiveUpdated:
    active: bool


# @dev Emitted when the maximum supply is lowered.
event MaxSupplyUpdated:
    max_supply: uint256


# @dev Emitted when the treasury changes.
event TreasuryUpdated:
    treasury: indexed(address)


# @dev Emitted when the current generation changes.
event GenerationUpdated:
    generation: uint16


# @dev Emitted once, when the `Mining` contract is wired.
event MiningSet:
    mining: indexed(address)


@deploy
@payable
def __init__(
    credits_: IERC20,
    treasury_: address,
    burn_proceeds_: bool,
    price_: uint256,
    max_supply_: uint256,
    metadata_base_: String[160],
    metadata_suffix_: String[32],
    contract_uri_: String[256],
):
    """
    @dev To omit the opcodes for checking the `msg.value`
         in the creation-time EVM bytecode, the constructor
         is declared as `payable`.
    @notice The `owner` role is assigned to `msg.sender`. The
            sale starts closed. The `erc721` minter role that
            snekmate grants to the deployer is revoked right away,
            since minting is only possible via `buy`.
    @param credits_ The 20-byte CREDITS ERC-20 address.
    @param treasury_ The 20-byte treasury address. It may be the
           zero address only if `burn_proceeds_` is `True`.
    @param burn_proceeds_ The Boolean variable that, if `True`,
           sends all CREDITS to `BURN_ADDRESS` instead.
    @param price_ The 32-byte price of one SCV in CREDITS.
    @param max_supply_ The 32-byte maximum supply.
    @param metadata_base_ The maximum 160-character token-URI prefix.
    @param metadata_suffix_ The maximum 32-character token-URI suffix.
    @param contract_uri_ The maximum 256-character ERC-7572 contract URI.
    """
    assert credits_.address != empty(address), "scv: credits is the zero address"
    assert burn_proceeds_ or treasury_ != empty(address), "scv: treasury is the zero address"
    assert price_ != empty(uint256), "scv: zero price"
    assert max_supply_ != empty(uint256), "scv: zero max supply"

    ownable.__init__()
    ownable_2step.__init__()
    erc721.__init__("Spacemine SCV", "SCV", "", "Spacemine SCV", "1")
    erc2981.__init__()
    metadata.__init__(metadata_base_, metadata_suffix_, contract_uri_)

    erc721.is_minter[msg.sender] = False
    log erc721.RoleMinterChanged(minter=msg.sender, status=False)

    credits = credits_
    burn_proceeds = burn_proceeds_
    self.treasury = treasury_
    self.price = price_
    self.max_supply = max_supply_
    self.current_generation = 1


@external
@view
def supportsInterface(interface_id: bytes4) -> bool:
    """
    @dev Returns `True` if this contract implements the
         interface defined by `interface_id`.
    @param interface_id The 4-byte interface identifier.
    @return bool The verification whether the contract
            implements the interface or not.
    """
    return interface_id in _SUPPORTED_INTERFACES


@external
@view
def tokenURI(token_id: uint256) -> String[512]:
    """
    @dev Returns `metadata_base || token_id || metadata_suffix`.
    @notice Throws if `token_id` is not a valid ERC-721 token.
            The declared bound is 512 to satisfy `IERC721Metadata`;
            the actual maximum length is 270 characters.
    @param token_id The 32-byte identifier of the token.
    @return String The token URI.
    """
    erc721._require_minted(token_id)
    return metadata._token_uri(token_id)


@external
@nonreentrant
def buy(quantity: uint256, max_total_cost: uint256) -> uint256:
    """
    @dev Buys `quantity` SCVs for `price * quantity` CREDITS and
         mints them with sequential IDs to `msg.sender`.
    @notice The caller must have approved this contract to spend
            the CREDITS. The CREDITS are pulled straight into the
            sink (`treasury` or `BURN_ADDRESS`), and the sink balance
            is measured before and after: if the sink receives less
            than the full cost (e.g. fee-on-transfer CREDITS), the call
            reverts. Tokens that do not return a `bool` are supported.
            SCVs are minted with `_mint` (no receiver callback), so a
            buyer contract gets no hook mid-transaction. The properties
            are unknown at this point anyway (see `reveal`).
    @param quantity The 32-byte number of SCVs to buy (1..`MAX_PER_TX`).
    @param max_total_cost The 32-byte maximum CREDITS the caller is
           willing to pay (protects against price changes).
    @return uint256 The 32-byte ID of the first minted SCV.
    """
    assert self.sale_active, "scv: sale not active"
    assert quantity != empty(uint256) and quantity <= MAX_PER_TX, "scv: invalid quantity"
    minted: uint256 = self.total_minted
    assert minted + quantity <= self.max_supply, "scv: max supply exceeded"
    total_cost: uint256 = self.price * quantity
    assert total_cost <= max_total_cost, "scv: cost exceeds max"

    # Effects: mint first, the CREDITS transfer below either
    # succeeds in full or reverts the whole transaction.
    first_id: uint256 = minted + 1
    self.total_minted = minted + quantity
    commit_block: uint256 = block.number + REVEAL_DELAY
    generation: uint16 = self.current_generation
    born_at: uint64 = convert(block.timestamp, uint64)
    for i: uint256 in range(quantity, bound=MAX_PER_TX):
        token_id: uint256 = first_id + i
        self._properties[token_id] = ISCV.SCVProperties(
            seed=empty(bytes32),
            revealed=False,
            model=0,
            mining_power=0,
            mineral_efficiency_bps=0,
            gas_efficiency_bps=0,
            generation=generation,
            born_at=born_at,
        )
        self.reveal_block[token_id] = commit_block
        erc721._mint(msg.sender, token_id)

    # Interactions: pull CREDITS into the sink and verify receipt.
    sink: address = self._sink()
    balance_before: uint256 = staticcall credits.balanceOf(sink)
    success: bool = extcall credits.transferFrom(msg.sender, sink, total_cost, default_return_value=True)
    assert success, "scv: credits transfer failed"
    assert staticcall credits.balanceOf(sink) >= balance_before + total_cost, "scv: credits fee not supported"

    log Purchased(buyer=msg.sender, first_token_id=first_id, quantity=quantity, total_cost=total_cost)
    return first_id


@external
@nonreentrant
def reveal(token_ids: DynArray[uint256, MAX_REVEAL_BATCH]):
    """
    @dev Reveals the properties of `token_ids`. Callable by anyone.
    @notice Each token must exist and `block.number` must be greater
            than its `reveal_block`. Already revealed tokens are
            skipped silently, so a front-run reveal cannot grief
            a batch. If the committed block hash can no longer be
            retrieved (`block_hash._block_hash` returns zero), the
            token receives the baseline stats with an empty seed.
    @param token_ids The array of up to 50 token IDs to reveal.
    """
    for token_id: uint256 in token_ids:
        erc721._require_minted(token_id)
        props: ISCV.SCVProperties = self._properties[token_id]
        if props.revealed:
            continue
        commit_block: uint256 = self.reveal_block[token_id]
        assert block.number > commit_block, "scv: reveal too early"

        hash: bytes32 = block_hash._block_hash(commit_block)
        baseline: bool = hash == empty(bytes32)
        if baseline:
            props.seed = empty(bytes32)
            props.model = 0
            props.mining_power = BASELINE_POWER
            props.mineral_efficiency_bps = BASELINE_EFFICIENCY_BPS
            props.gas_efficiency_bps = BASELINE_EFFICIENCY_BPS
        else:
            props = self._roll(keccak256(abi_encode(hash, token_id, self)), props)
        props.revealed = True
        self._properties[token_id] = props

        log Revealed(
            token_id=token_id,
            seed=props.seed,
            model=props.model,
            mining_power=props.mining_power,
            mineral_efficiency_bps=props.mineral_efficiency_bps,
            gas_efficiency_bps=props.gas_efficiency_bps,
            baseline=baseline,
        )
        log IERC4906.MetadataUpdate(_tokenId=token_id)


@external
def record_mined(token_id: uint256, kind: uint8, amount: uint256):
    """
    @dev Adds `amount` of resource `kind` to the lifetime stats
         of `token_id` and emits ERC-4906 `MetadataUpdate`.
    @notice Only the wired `Mining` contract can call this function.
    @param token_id The 32-byte identifier of the token.
    @param kind The 1-byte resource kind (0 = mineral, 1 = gas).
    @param amount The 32-byte amount that has been mined.
    """
    assert msg.sender == self.mining, "scv: caller is not mining"
    erc721._require_minted(token_id)
    total: uint256 = empty(uint256)
    if kind == KIND_MINERAL:
        total = self.lifetime_minerals[token_id] + amount
        self.lifetime_minerals[token_id] = total
    elif kind == KIND_GAS:
        total = self.lifetime_gas[token_id] + amount
        self.lifetime_gas[token_id] = total
    else:
        raise "scv: invalid kind"
    log LifetimeStatsUpdated(token_id=token_id, kind=kind, amount=amount, lifetime_total=total)
    log IERC4906.MetadataUpdate(_tokenId=token_id)


@external
@view
def properties(token_id: uint256) -> ISCV.SCVProperties:
    """
    @dev Returns the properties of `token_id`.
    @notice Throws if `token_id` does not exist. Before the reveal,
            only `generation` and `born_at` are set.
    @param token_id The 32-byte identifier of the token.
    @return SCVProperties The properties struct.
    """
    erc721._require_minted(token_id)
    return self._properties[token_id]


@external
@view
def is_revealed(token_id: uint256) -> bool:
    """
    @dev Returns whether the properties of `token_id` are revealed.
    @notice Returns `False` for non-existent tokens.
    @param token_id The 32-byte identifier of the token.
    @return bool The verification whether `token_id` is revealed.
    """
    return self._properties[token_id].revealed


@external
@view
def mining_weight(token_id: uint256, kind: uint8) -> uint256:
    """
    @dev Returns `mining_power * efficiency_bps(kind) / 10_000`.
    @notice Throws if `token_id` is not revealed or `kind` is invalid.
            The minimum weight is 100 * 5,000 / 10,000 = 50.
    @param token_id The 32-byte identifier of the token.
    @param kind The 1-byte resource kind (0 = mineral, 1 = gas).
    @return uint256 The 32-byte mining weight.
    """
    props: ISCV.SCVProperties = self._properties[token_id]
    assert props.revealed, "scv: not revealed"
    efficiency: uint16 = empty(uint16)
    if kind == KIND_MINERAL:
        efficiency = props.mineral_efficiency_bps
    elif kind == KIND_GAS:
        efficiency = props.gas_efficiency_bps
    else:
        raise "scv: invalid kind"
    return convert(props.mining_power, uint256) * convert(efficiency, uint256) // _BPS


@external
def set_price(new_price: uint256):
    """
    @dev Sets the price of one SCV in CREDITS.
    @notice Only the `owner` can call this function. Buyers are
            protected against changes by `max_total_cost`.
    @param new_price The 32-byte non-zero price.
    """
    ownable._check_owner()
    assert new_price != empty(uint256), "scv: zero price"
    self.price = new_price
    log PriceUpdated(price=new_price)


@external
def set_sale_active(active: bool):
    """
    @dev Opens or closes the sale.
    @notice Only the `owner` can call this function.
    @param active The Boolean variable that sets the status.
    """
    ownable._check_owner()
    self.sale_active = active
    log SaleActiveUpdated(active=active)


@external
def set_max_supply(new_max_supply: uint256):
    """
    @dev Lowers the maximum supply.
    @notice Only the `owner` can call this function. The supply
            can only decrease and never below `total_minted`.
    @param new_max_supply The 32-byte new maximum supply.
    """
    ownable._check_owner()
    assert new_max_supply <= self.max_supply, "scv: max supply can only decrease"
    assert new_max_supply >= self.total_minted, "scv: max supply below minted"
    self.max_supply = new_max_supply
    log MaxSupplyUpdated(max_supply=new_max_supply)


@external
def set_treasury(new_treasury: address):
    """
    @dev Sets the treasury that receives CREDITS.
    @notice Only the `owner` can call this function. Not available
            when `burn_proceeds` is enabled.
    @param new_treasury The 20-byte non-zero treasury address.
    """
    ownable._check_owner()
    assert not burn_proceeds, "scv: proceeds are burned"
    assert new_treasury != empty(address), "scv: treasury is the zero address"
    self.treasury = new_treasury
    log TreasuryUpdated(treasury=new_treasury)


@external
def set_generation(generation: uint16):
    """
    @dev Sets the generation stamped on newly minted SCVs.
    @notice Only the `owner` can call this function. Existing
            SCVs keep their generation.
    @param generation The 2-byte generation number.
    """
    ownable._check_owner()
    self.current_generation = generation
    log GenerationUpdated(generation=generation)


@external
def set_mining(mining_: address):
    """
    @dev Wires the `Mining` contract that may write lifetime stats.
    @notice Only the `owner` can call this function, and only once:
            a re-pointable writer would let the owner forge lifetime
            stats and, worse, break `Mining`'s wiring check.
    @param mining_ The 20-byte `Mining` address.
    """
    ownable._check_owner()
    assert self.mining == empty(address), "scv: mining already set"
    assert mining_ != empty(address), "scv: mining is the zero address"
    self.mining = mining_
    log MiningSet(mining=mining_)


@external
def set_metadata_uri(base_: String[160], suffix_: String[32]):
    """
    @dev Sets the token-URI prefix and suffix and emits ERC-4906
         `BatchMetadataUpdate(0, type(uint256).max)`.
    @notice Only the `owner` can call this function.
    @param base_ The maximum 160-character token-URI prefix.
    @param suffix_ The maximum 32-character token-URI suffix.
    """
    ownable._check_owner()
    metadata._set_metadata_uri(base_, suffix_)
    log IERC4906.BatchMetadataUpdate(_fromTokenId=empty(uint256), _toTokenId=max_value(uint256))


@external
def set_contract_uri(contract_uri_: String[256]):
    """
    @dev Sets the ERC-7572 contract URI and emits `ContractURIUpdated`.
    @notice Only the `owner` can call this function.
    @param contract_uri_ The maximum 256-character contract URI.
    """
    ownable._check_owner()
    metadata._set_contract_uri(contract_uri_)


@internal
@view
def _sink() -> address:
    """
    @dev Returns the address that receives CREDITS.
    @return address The 20-byte sink address.
    """
    if burn_proceeds:
        return BURN_ADDRESS
    return self.treasury


@internal
@pure
def _roll(seed: bytes32, props: ISCV.SCVProperties) -> ISCV.SCVProperties:
    """
    @dev Rolls the random properties from `seed`. Each property
         uses a distinct 64-bit window of the seed.
    @param seed The 32-byte seed.
    @param props The properties to fill (keeps `generation` and `born_at`).
    @return SCVProperties The rolled properties.
    """
    rand: uint256 = convert(seed, uint256)
    result: ISCV.SCVProperties = props
    result.seed = seed

    tier_roll: uint256 = rand % _BPS
    tier: uint256 = 3
    for i: uint256 in range(4):
        if tier_roll < _TIER_THRESHOLDS[i]:
            tier = i
            break
    result.model = convert(tier, uint8)

    power_min: uint256 = _TIER_POWER_MIN[tier]
    power_span: uint256 = _TIER_POWER_MAX[tier] - power_min + 1
    result.mining_power = convert(power_min + (rand >> 64) % power_span, uint16)

    efficiency_span: uint256 = convert(MAX_EFFICIENCY_BPS - MIN_EFFICIENCY_BPS, uint256) + 1
    min_efficiency: uint256 = convert(MIN_EFFICIENCY_BPS, uint256)
    result.mineral_efficiency_bps = convert(min_efficiency + (rand >> 128) % efficiency_span, uint16)
    result.gas_efficiency_bps = convert(min_efficiency + (rand >> 192) % efficiency_span, uint16)
    return result
