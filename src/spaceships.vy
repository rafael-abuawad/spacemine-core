# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Spacemine Spaceships Collection
@custom:contract-name spaceships
@license MIT
@notice ERC-1155 collection where every token ID is a ship type.
        Ships of the same type are fungible, so on-chain properties
        belong to the type. Ships are bought exclusively with MNRL and
        GAS (never CREDITS or ETH: no function is `payable`), which
        makes this contract the sink for mined resources. By default,
        payments are burned via `burn_from` (the buyer approves this
        contract on MNRL/GAS). Optionally, the `owner` can switch to
        treasury mode, in which payments are transferred to `treasury`.
        Holders can transfer, approve, and burn freely. Purchase is the
        only way to mint: snekmate's `safe_mint`, `safe_mint_batch`,
        `set_minter`, `set_uri`, and `uri` are not exported. Combat and
        capacity stats are immutable after creation.
"""


# @dev We import and implement the `IERC165` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC165
implements: IERC165


# @dev We import the `IERC20` interface, which is a built-in
# interface of the Vyper compiler, for treasury-mode payments.
from ethereum.ercs import IERC20


# @dev We import and implement the snekmate ERC-1155 interfaces.
from snekmate.tokens.interfaces import IERC1155
implements: IERC1155
from snekmate.tokens.interfaces import IERC1155MetadataURI
implements: IERC1155MetadataURI
from snekmate.extensions.interfaces import IERC2981
implements: IERC2981


# @dev We import the project-specific `IResourceToken` interface
# for burn-mode payments.
from .interfaces import IResourceToken


# @dev We import and initialise the `ownable` module and
# use the two-step ownership transfer of `ownable_2step`.
from snekmate.auth import ownable
initializes: ownable
from snekmate.auth import ownable_2step
initializes: ownable_2step[ownable := ownable]


# @dev We import and initialise the `erc1155` module.
from snekmate.tokens import erc1155
initializes: erc1155[ownable := ownable]


# @dev We import and initialise the `erc2981` module.
from snekmate.extensions import erc2981
initializes: erc2981[ownable := ownable]


# @dev We import and initialise the shared metadata module.
from .modules import metadata
initializes: metadata


exports: (
    erc1155.safeTransferFrom,
    erc1155.safeBatchTransferFrom,
    erc1155.setApprovalForAll,
    erc1155.balanceOf,
    erc1155.balanceOfBatch,
    erc1155.isApprovedForAll,
    erc1155.exists,
    erc1155.total_supply,
    erc1155.burn,
    erc1155.burn_batch,
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
_SUPPORTED_INTERFACES: constant(bytes4[4]) = [
    0x01FFC9A7, # The ERC-165 identifier for ERC-165.
    0xD9B67A26, # The ERC-165 identifier for ERC-1155.
    0x0E89341C, # The ERC-165 identifier for the ERC-1155 metadata extension.
    0x2A55205A, # The ERC-165 identifier for ERC-2981.
]


# @dev Ship classes (FIGHTER = 1, FRIGATE = 2, FREIGHTER = 4,
# CRUISER = 8, CARRIER = 16). Exactly one member is set per type.
flag ShipClass:
    FIGHTER
    FRIGATE
    FREIGHTER
    CRUISER
    CARRIER


# @dev The maximum number of ships per type in one purchase.
MAX_PER_TX: public(constant(uint256)) = 50


# @dev The maximum number of entries in one `buy_batch` call.
MAX_BATCH_TYPES: public(constant(uint256)) = 16


# @dev The maximum number of ship types (bounds the `URI` refresh loop).
MAX_SHIP_TYPES: public(constant(uint256)) = 64


# @dev Ship type properties. The field order is part of the ABI.
struct ShipType:
    name: String[32]
    ship_class: ShipClass
    mineral_cost: uint256
    gas_cost: uint256
    max_supply: uint256
    minted: uint256
    active: bool
    hull: uint16
    shield: uint16
    attack: uint16
    speed: uint16
    cargo: uint32
    created_at: uint64


# @dev Returns the MNRL token.
minerals: public(immutable(address))


# @dev Returns the GAS token.
gas: public(immutable(address))


# @dev Returns the treasury used in treasury mode.
treasury: public(address)


# @dev Returns whether payments go to `treasury` (`True`) or are
# burned (`False`, the default).
treasury_mode: public(bool)


# @dev Returns the number of ship types (IDs are 1-based).
ship_type_count: public(uint256)


# @dev Mapping from ship type ID to its properties.
_ship_types: HashMap[uint256, ShipType]


# @dev Emitted when a ship type is created.
event ShipTypeCreated:
    ship_id: indexed(uint256)
    name: String[32]
    ship_class: ShipClass
    mineral_cost: uint256
    gas_cost: uint256
    max_supply: uint256


# @dev Emitted when a ship type is (de)activated.
event ShipActiveUpdated:
    ship_id: indexed(uint256)
    active: bool


# @dev Emitted when the prices of a ship type change.
event ShipPricesUpdated:
    ship_id: indexed(uint256)
    mineral_cost: uint256
    gas_cost: uint256


# @dev Emitted when the maximum supply of a ship type is lowered.
event ShipMaxSupplyUpdated:
    ship_id: indexed(uint256)
    max_supply: uint256


# @dev Emitted when ships are bought.
event ShipsPurchased:
    buyer: indexed(address)
    ship_id: indexed(uint256)
    amount: uint256
    mineral_paid: uint256
    gas_paid: uint256


# @dev Emitted when the treasury changes.
event TreasuryUpdated:
    treasury: indexed(address)


# @dev Emitted when the payment mode changes.
event TreasuryModeUpdated:
    treasury_mode: bool


@deploy
@payable
def __init__(
    minerals_: address,
    gas_: address,
    treasury_: address,
    metadata_base_: String[160],
    metadata_suffix_: String[32],
    contract_uri_: String[256],
):
    """
    @dev To omit the opcodes for checking the `msg.value`
         in the creation-time EVM bytecode, the constructor
         is declared as `payable`.
    @notice The `owner` role is assigned to `msg.sender`. The
            unused `erc1155` minter role is revoked right away.
            Payments are burned until treasury mode is enabled.
    @param minerals_ The 20-byte MNRL token address.
    @param gas_ The 20-byte GAS token address.
    @param treasury_ The 20-byte treasury address (may be zero
           while treasury mode is off).
    @param metadata_base_ The maximum 160-character token-URI prefix.
    @param metadata_suffix_ The maximum 32-character token-URI suffix.
    @param contract_uri_ The maximum 256-character ERC-7572 contract URI.
    """
    assert minerals_ != empty(address) and gas_ != empty(address), "spaceships: zero address"
    ownable.__init__()
    ownable_2step.__init__()
    erc1155.__init__("")
    erc2981.__init__()
    metadata.__init__(metadata_base_, metadata_suffix_, contract_uri_)

    erc1155.is_minter[msg.sender] = False
    log erc1155.RoleMinterChanged(minter=msg.sender, status=False)

    minerals = minerals_
    gas = gas_
    self.treasury = treasury_


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
def uri(id: uint256) -> String[512]:
    """
    @dev Returns `metadata_base || id || metadata_suffix`.
    @notice There is no `{id}` placeholder: `web3://` renderers
            need the literal ID. Throws if the ship type does not
            exist. The declared bound is 512 to satisfy
            `IERC1155MetadataURI`; the actual maximum is 270.
    @param id The 32-byte identifier of the ship type.
    @return String The token URI.
    """
    self._require_ship(id)
    return metadata._token_uri(id)


@external
@view
def ship_type(ship_id: uint256) -> ShipType:
    """
    @dev Returns the properties of `ship_id`.
    @notice Throws if the ship type does not exist.
    @param ship_id The 32-byte identifier of the ship type.
    @return ShipType The ship type struct.
    """
    self._require_ship(ship_id)
    return self._ship_types[ship_id]


@external
@view
def quote(ship_id: uint256, amount: uint256) -> (uint256, uint256):
    """
    @dev Returns the MNRL and GAS cost of `amount` ships of `ship_id`.
    @notice Throws if the ship type does not exist.
    @param ship_id The 32-byte identifier of the ship type.
    @param amount The 32-byte number of ships.
    @return uint256 The 32-byte MNRL cost.
    @return uint256 The 32-byte GAS cost.
    """
    self._require_ship(ship_id)
    ship: ShipType = self._ship_types[ship_id]
    return (ship.mineral_cost * amount, ship.gas_cost * amount)


@external
@nonreentrant
def create_ship_type(
    name: String[32],
    ship_class: ShipClass,
    mineral_cost: uint256,
    gas_cost: uint256,
    max_supply: uint256,
    hull: uint16,
    shield: uint16,
    attack: uint16,
    speed: uint16,
    cargo: uint32,
) -> uint256:
    """
    @dev Creates a new ship type with the next sequential ID.
    @notice Only the `owner` can call this function. The type starts
            active. Stats are immutable; prices, `active`, and
            (downwards only) `max_supply` can be changed later.
            Emits `ShipTypeCreated` and the ERC-1155 `URI` event.
    @param name The maximum 32-character non-empty name.
    @param ship_class The `ShipClass` (exactly one member).
    @param mineral_cost The 32-byte MNRL cost per ship.
    @param gas_cost The 32-byte GAS cost per ship. At least one
           of the two costs must be non-zero.
    @param max_supply The 32-byte maximum supply (0 = unlimited).
    @param hull The 2-byte hull stat.
    @param shield The 2-byte shield stat.
    @param attack The 2-byte attack stat.
    @param speed The 2-byte speed stat.
    @param cargo The 4-byte cargo capacity.
    @return uint256 The 32-byte ID of the new ship type.
    """
    ownable._check_owner()
    assert len(name) != empty(uint256), "spaceships: empty name"
    # Out-of-range flag values are rejected by the ABI decoder; this
    # rejects the empty flag and combinations of several classes.
    class_bits: uint256 = convert(ship_class, uint256)
    assert class_bits != empty(uint256) and class_bits & (class_bits - 1) == empty(uint256), "spaceships: invalid class"
    assert mineral_cost != empty(uint256) or gas_cost != empty(uint256), "spaceships: free ship"
    ship_id: uint256 = self.ship_type_count + 1
    assert ship_id <= MAX_SHIP_TYPES, "spaceships: too many ship types"
    self.ship_type_count = ship_id
    self._ship_types[ship_id] = ShipType(
        name=name,
        ship_class=ship_class,
        mineral_cost=mineral_cost,
        gas_cost=gas_cost,
        max_supply=max_supply,
        minted=0,
        active=True,
        hull=hull,
        shield=shield,
        attack=attack,
        speed=speed,
        cargo=cargo,
        created_at=convert(block.timestamp, uint64),
    )
    log ShipTypeCreated(
        ship_id=ship_id,
        name=name,
        ship_class=ship_class,
        mineral_cost=mineral_cost,
        gas_cost=gas_cost,
        max_supply=max_supply,
    )
    log IERC1155.URI(_value=metadata._token_uri(ship_id), _id=ship_id)
    return ship_id


@external
@nonreentrant
def set_ship_active(ship_id: uint256, active: bool):
    """
    @dev Enables or disables purchases of `ship_id`.
    @notice Only the `owner` can call this function.
    @param ship_id The 32-byte identifier of the ship type.
    @param active The Boolean variable that sets the status.
    """
    ownable._check_owner()
    self._require_ship(ship_id)
    self._ship_types[ship_id].active = active
    log ShipActiveUpdated(ship_id=ship_id, active=active)


@external
@nonreentrant
def set_ship_prices(ship_id: uint256, mineral_cost: uint256, gas_cost: uint256):
    """
    @dev Sets the per-ship MNRL and GAS cost of `ship_id`.
    @notice Only the `owner` can call this function. Buyers are
            protected by `max_mineral_cost`/`max_gas_cost`.
    @param ship_id The 32-byte identifier of the ship type.
    @param mineral_cost The 32-byte MNRL cost per ship.
    @param gas_cost The 32-byte GAS cost per ship. At least one
           of the two costs must be non-zero.
    """
    ownable._check_owner()
    self._require_ship(ship_id)
    assert mineral_cost != empty(uint256) or gas_cost != empty(uint256), "spaceships: free ship"
    self._ship_types[ship_id].mineral_cost = mineral_cost
    self._ship_types[ship_id].gas_cost = gas_cost
    log ShipPricesUpdated(ship_id=ship_id, mineral_cost=mineral_cost, gas_cost=gas_cost)


@external
@nonreentrant
def set_ship_max_supply(ship_id: uint256, max_supply: uint256):
    """
    @dev Lowers the maximum supply of `ship_id`.
    @notice Only the `owner` can call this function. The supply can
            only decrease (unlimited counts as infinite), can never
            become unlimited again, and never drops below `minted`.
    @param ship_id The 32-byte identifier of the ship type.
    @param max_supply The 32-byte new non-zero maximum supply.
    """
    ownable._check_owner()
    self._require_ship(ship_id)
    ship: ShipType = self._ship_types[ship_id]
    assert max_supply != empty(uint256), "spaceships: max supply can only decrease"
    assert (
        ship.max_supply == empty(uint256) or max_supply <= ship.max_supply
    ), "spaceships: max supply can only decrease"
    assert max_supply >= ship.minted, "spaceships: max supply below minted"
    self._ship_types[ship_id].max_supply = max_supply
    log ShipMaxSupplyUpdated(ship_id=ship_id, max_supply=max_supply)


@external
@nonreentrant
def set_treasury(new_treasury: address):
    """
    @dev Sets the treasury used in treasury mode.
    @notice Only the `owner` can call this function.
    @param new_treasury The 20-byte non-zero treasury address.
    """
    ownable._check_owner()
    assert new_treasury != empty(address), "spaceships: treasury is the zero address"
    self.treasury = new_treasury
    log TreasuryUpdated(treasury=new_treasury)


@external
@nonreentrant
def set_treasury_mode(enabled: bool):
    """
    @dev Switches between burning payments (`False`) and sending
         them to `treasury` (`True`).
    @notice Only the `owner` can call this function. A treasury
            must be set before treasury mode can be enabled.
    @param enabled The Boolean variable that sets the mode.
    """
    ownable._check_owner()
    assert not enabled or self.treasury != empty(address), "spaceships: treasury is the zero address"
    self.treasury_mode = enabled
    log TreasuryModeUpdated(treasury_mode=enabled)


@external
@nonreentrant
def set_metadata_uri(base_: String[160], suffix_: String[32]):
    """
    @dev Sets the token-URI prefix and suffix and emits the
         ERC-1155 `URI` event for every existing ship type
         (bounded by `MAX_SHIP_TYPES`).
    @notice Only the `owner` can call this function.
    @param base_ The maximum 160-character token-URI prefix.
    @param suffix_ The maximum 32-character token-URI suffix.
    """
    ownable._check_owner()
    metadata._set_metadata_uri(base_, suffix_)
    for ship_id: uint256 in range(1, MAX_SHIP_TYPES + 1):
        if ship_id > self.ship_type_count:
            break
        log IERC1155.URI(_value=metadata._token_uri(ship_id), _id=ship_id)


@external
@nonreentrant
def set_contract_uri(contract_uri_: String[256]):
    """
    @dev Sets the ERC-7572 contract URI and emits `ContractURIUpdated`.
    @notice Only the `owner` can call this function.
    @param contract_uri_ The maximum 256-character contract URI.
    """
    ownable._check_owner()
    metadata._set_contract_uri(contract_uri_)


@external
@nonreentrant
def buy(ship_id: uint256, amount: uint256, max_mineral_cost: uint256, max_gas_cost: uint256):
    """
    @dev Buys `amount` ships of `ship_id` for MNRL and/or GAS.
    @notice The caller must have approved this contract on MNRL
            and/or GAS for the respective costs. Resources with a
            cost of zero are skipped. All state updates and payments
            happen before the mint. The mint invokes the ERC-1155
            receiver hook, so contract buyers must implement
            `onERC1155Received`. The function is `@nonreentrant`,
            so the hook cannot re-enter any purchase or admin path.
    @param ship_id The 32-byte identifier of the ship type.
    @param amount The 32-byte number of ships (1..`MAX_PER_TX`).
    @param max_mineral_cost The 32-byte maximum MNRL to pay.
    @param max_gas_cost The 32-byte maximum GAS to pay.
    """
    mineral_cost: uint256 = empty(uint256)
    gas_cost: uint256 = empty(uint256)
    mineral_cost, gas_cost = self._reserve(ship_id, amount)
    assert mineral_cost <= max_mineral_cost, "spaceships: mineral cost exceeds max"
    assert gas_cost <= max_gas_cost, "spaceships: gas cost exceeds max"

    self._pay(msg.sender, mineral_cost, gas_cost)
    log ShipsPurchased(buyer=msg.sender, ship_id=ship_id, amount=amount, mineral_paid=mineral_cost, gas_paid=gas_cost)
    erc1155._safe_mint(msg.sender, ship_id, amount, b"")


@external
@nonreentrant
def buy_batch(
    ship_ids: DynArray[uint256, MAX_BATCH_TYPES],
    amounts: DynArray[uint256, MAX_BATCH_TYPES],
    max_mineral_cost: uint256,
    max_gas_cost: uint256,
):
    """
    @dev Batched version of `buy` with one aggregated payment
         per resource.
    @notice `ship_ids` and `amounts` must have the same, non-zero
            length. Duplicate IDs are allowed and are checked
            cumulatively against the supply cap. The mint invokes
            `onERC1155BatchReceived` on contract buyers.
    @param ship_ids The array of up to `MAX_BATCH_TYPES` ship type IDs.
    @param amounts The array of amounts, matching `ship_ids`.
    @param max_mineral_cost The 32-byte maximum total MNRL to pay.
    @param max_gas_cost The 32-byte maximum total GAS to pay.
    """
    assert len(ship_ids) == len(amounts), "spaceships: length mismatch"
    assert len(ship_ids) != empty(uint256), "spaceships: empty batch"
    mineral_total: uint256 = empty(uint256)
    gas_total: uint256 = empty(uint256)
    idx: uint256 = empty(uint256)
    for ship_id: uint256 in ship_ids:
        mineral_cost: uint256 = empty(uint256)
        gas_cost: uint256 = empty(uint256)
        mineral_cost, gas_cost = self._reserve(ship_id, amounts[idx])
        mineral_total += mineral_cost
        gas_total += gas_cost
        log ShipsPurchased(
            buyer=msg.sender, ship_id=ship_id, amount=amounts[idx], mineral_paid=mineral_cost, gas_paid=gas_cost
        )
        idx = unsafe_add(idx, 1)
    assert mineral_total <= max_mineral_cost, "spaceships: mineral cost exceeds max"
    assert gas_total <= max_gas_cost, "spaceships: gas cost exceeds max"

    self._pay(msg.sender, mineral_total, gas_total)
    erc1155._safe_mint_batch(msg.sender, ship_ids, amounts, b"")


@internal
@view
def _require_ship(ship_id: uint256):
    """
    @dev Throws if `ship_id` does not exist.
    @param ship_id The 32-byte identifier of the ship type.
    """
    assert ship_id != empty(uint256) and ship_id <= self.ship_type_count, "spaceships: unknown ship type"


@internal
def _reserve(ship_id: uint256, amount: uint256) -> (uint256, uint256):
    """
    @dev Checks a purchase of `amount` ships of `ship_id`, books it
         against the supply cap, and returns its costs.
    @param ship_id The 32-byte identifier of the ship type.
    @param amount The 32-byte number of ships.
    @return uint256 The 32-byte MNRL cost.
    @return uint256 The 32-byte GAS cost.
    """
    self._require_ship(ship_id)
    ship: ShipType = self._ship_types[ship_id]
    assert ship.active, "spaceships: ship type inactive"
    assert amount != empty(uint256) and amount <= MAX_PER_TX, "spaceships: invalid amount"
    minted: uint256 = ship.minted + amount
    assert ship.max_supply == empty(uint256) or minted <= ship.max_supply, "spaceships: max supply exceeded"
    self._ship_types[ship_id].minted = minted
    return (ship.mineral_cost * amount, ship.gas_cost * amount)


@internal
def _pay(payer: address, mineral_cost: uint256, gas_cost: uint256):
    """
    @dev Collects the MNRL and GAS payment from `payer`, either by
         burning it or by transferring it to `treasury`.
    @notice Only the trusted MNRL and GAS contracts are called.
    @param payer The 20-byte payer address.
    @param mineral_cost The 32-byte MNRL amount.
    @param gas_cost The 32-byte GAS amount.
    """
    if mineral_cost != empty(uint256):
        self._pay_one(minerals, payer, mineral_cost)
    if gas_cost != empty(uint256):
        self._pay_one(gas, payer, gas_cost)


@internal
def _pay_one(token: address, payer: address, amount: uint256):
    """
    @dev Collects `amount` of `token` from `payer`.
    @param token The 20-byte resource token address.
    @param payer The 20-byte payer address.
    @param amount The 32-byte amount.
    """
    if self.treasury_mode:
        success: bool = extcall IERC20(token).transferFrom(payer, self.treasury, amount, default_return_value=True)
        assert success, "spaceships: payment failed"
    else:
        extcall IResourceToken(token).burn_from(payer, amount)
