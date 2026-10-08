# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Spacemine Mining (Resource Nodes + Unipool-Style Staking)
@custom:contract-name Mining
@license MIT
@notice Holds every resource node (mineral patch or gas geyser) and
        lets SCV holders stake revealed SCVs into them. Each node
        emits `emission_rate` resource wei per second, split pro rata
        by staked weight (Synthetix `StakingRewards` / Unipool math),
        until its finite reserve is exhausted. Deliberate changes to
        the classic design:
        - time only counts while `total_weight > 0`, so idle nodes
          do not burn reserve and no rewards are stranded,
        - emission is capped by `reserve_remaining`, so the total
          minted per node never exceeds `reserve_total`,
        - accounting is per SCV (each staked SCV keeps its own
          `reward_per_weight_paid`), so rewards and lifetime stats
          follow the token.
        Staked SCVs are escrowed in this contract and can only ever
        be returned to the address that staked them. `unstake` and
        `claim` cannot be blocked by pausing, node deactivation, or
        depletion. No admin function can change a node's reserve or
        rate, move escrowed SCVs, or mint resources.
"""


# @dev We import the `IERC721` interface, which is a
# built-in interface of the Vyper compiler, to escrow SCVs.
from ethereum.ercs import IERC721


# @dev We import and implement the `IERC721Receiver` interface
# so that accidental `safeTransferFrom`s into escrow revert
# with a clear message.
from snekmate.tokens.interfaces import IERC721Receiver
implements: IERC721Receiver


# @dev We import the project-specific interfaces.
from .interfaces import ISCV
from .interfaces import IPlanets
from .interfaces import IResourceToken
from .interfaces import IMining
implements: IMining


# @dev We import and initialise the `ownable` module and
# use the two-step ownership transfer of `ownable_2step`.
from snekmate.auth import ownable
initializes: ownable
from snekmate.auth import ownable_2step
initializes: ownable_2step[ownable := ownable]


# @dev We import and initialise the `pausable` module.
from snekmate.utils import pausable
initializes: pausable


exports: (
    ownable.owner,
    ownable_2step.pending_owner,
    ownable_2step.transfer_ownership,
    ownable_2step.accept_ownership,
    ownable_2step.renounce_ownership,
    pausable.paused,
)


# @dev Resource kinds.
KIND_MINERAL: public(constant(uint8)) = 0
KIND_GAS: public(constant(uint8)) = 1


# @dev The maximum number of SCV slots per node.
MAX_SLOTS: public(constant(uint256)) = 8


# @dev The maximum number of SCVs per `unstake`/`claim`/`pending_many` call.
MAX_BATCH: public(constant(uint256)) = 32


# @dev The maximum number of SCVs a single address can have staked.
MAX_STAKED_PER_OWNER: public(constant(uint256)) = 128


# @dev The fixed-point precision of `reward_per_weight_stored`.
PRECISION: public(constant(uint256)) = 10**18


# @dev The upper bound for `base_reserve` (10^12 tokens with 18 decimals).
MAX_BASE_RESERVE: public(constant(uint256)) = 10**30


# @dev The upper bound for `base_rate` (10^6 tokens per second).
MAX_EMISSION_RATE: public(constant(uint256)) = 10**24


# @dev The basis-point denominator.
_BPS: constant(uint256) = 10_000


# @dev Returns the SCV collection.
scv: public(immutable(address))


# @dev Returns the Planets collection.
planets: public(immutable(address))


# @dev Returns the MNRL token.
minerals: public(immutable(address))


# @dev Returns the GAS token.
gas: public(immutable(address))


# @dev Returns the number of nodes created so far (IDs are 1-based).
node_count: public(uint256)


# @dev Returns the total amount minted (paid out) by each node.
paid_out: public(HashMap[uint256, uint256])


# @dev Mapping from node ID to node state.
_nodes: HashMap[uint256, IMining.Node]


# @dev Mapping from SCV ID to its staking position.
_positions: HashMap[uint256, IMining.Position]


# @dev Mapping from node ID to the staked SCV IDs.
_node_scvs: HashMap[uint256, DynArray[uint256, MAX_SLOTS]]


# @dev Mapping from owner to the staked SCV IDs.
_staked_by: HashMap[address, DynArray[uint256, MAX_STAKED_PER_OWNER]]


# @dev Mapping from SCV ID to its index in `_node_scvs`.
_node_scv_index: HashMap[uint256, uint256]


# @dev Mapping from SCV ID to its index in `_staked_by`.
_staked_by_index: HashMap[uint256, uint256]


# @dev Emitted when a node is created.
event NodeCreated:
    node_id: indexed(uint256)
    planet_id: indexed(uint256)
    kind: uint8
    max_slots: uint8
    reserve_total: uint256
    emission_rate: uint256


# @dev Emitted when a node is (de)activated for new stakes.
event NodeActiveUpdated:
    node_id: indexed(uint256)
    active: bool


# @dev Emitted when the reserve of a node reaches zero.
event NodeDepleted:
    node_id: indexed(uint256)


# @dev Emitted when an SCV is staked.
event Staked:
    owner: indexed(address)
    node_id: indexed(uint256)
    scv_id: indexed(uint256)
    weight: uint256


# @dev Emitted when an SCV is unstaked.
event Unstaked:
    owner: indexed(address)
    node_id: indexed(uint256)
    scv_id: indexed(uint256)
    reward: uint256


# @dev Emitted when the rewards of a staked SCV are claimed.
event Claimed:
    owner: indexed(address)
    node_id: indexed(uint256)
    scv_id: indexed(uint256)
    reward: uint256


@deploy
@payable
def __init__(scv_: address, planets_: address, minerals_: address, gas_: address):
    """
    @dev To omit the opcodes for checking the `msg.value`
         in the creation-time EVM bytecode, the constructor
         is declared as `payable`.
    @notice The `owner` role is assigned to `msg.sender`.
    @param scv_ The 20-byte SCV collection address.
    @param planets_ The 20-byte Planets collection address.
    @param minerals_ The 20-byte MNRL token address.
    @param gas_ The 20-byte GAS token address.
    """
    assert scv_ != empty(address), "mining: zero address"
    assert planets_ != empty(address), "mining: zero address"
    assert minerals_ != empty(address), "mining: zero address"
    assert gas_ != empty(address), "mining: zero address"
    ownable.__init__()
    ownable_2step.__init__()
    pausable.__init__()
    scv = scv_
    planets = planets_
    minerals = minerals_
    gas = gas_


@external
@nonreentrant
def create_node(
    planet_id: uint256, kind: uint8, max_slots: uint8, base_reserve: uint256, base_rate: uint256
) -> uint256:
    """
    @dev Creates a resource node on `planet_id` and registers it there.
    @notice Only the `owner` can call this function. The reserve is
            scaled by the planet's richness for `kind`:
            `reserve = base_reserve * richness_bps / 10_000`.
            Reserve and rate are immutable after creation.
    @param planet_id The 32-byte identifier of the planet.
    @param kind The 1-byte resource kind (0 = mineral, 1 = gas).
    @param max_slots The 1-byte number of SCV slots (1..`MAX_SLOTS`).
    @param base_reserve The 32-byte unscaled reserve (1..`MAX_BASE_RESERVE`).
    @param base_rate The 32-byte emission rate in resource wei per
           second (1..`MAX_EMISSION_RATE`).
    @return uint256 The 32-byte ID of the new node.
    """
    ownable._check_owner()
    assert kind <= KIND_GAS, "mining: invalid kind"
    assert max_slots != empty(uint8) and convert(max_slots, uint256) <= MAX_SLOTS, "mining: invalid slots"
    assert base_reserve != empty(uint256) and base_reserve <= MAX_BASE_RESERVE, "mining: invalid reserve"
    assert base_rate != empty(uint256) and base_rate <= MAX_EMISSION_RATE, "mining: invalid rate"

    world: IPlanets.Planet = staticcall IPlanets(planets).planet(planet_id)
    richness: uint16 = world.mineral_richness_bps
    if kind == KIND_GAS:
        richness = world.gas_richness_bps
    reserve: uint256 = base_reserve * convert(richness, uint256) // _BPS
    assert reserve != empty(uint256), "mining: zero reserve"

    node_id: uint256 = self.node_count + 1
    self.node_count = node_id
    self._nodes[node_id] = IMining.Node(
        planet_id=planet_id,
        kind=kind,
        max_slots=max_slots,
        occupied=0,
        reserve_total=reserve,
        reserve_remaining=reserve,
        emission_rate=base_rate,
        total_weight=0,
        reward_per_weight_stored=0,
        last_update=convert(block.timestamp, uint64),
        active=True,
    )
    log NodeCreated(
        node_id=node_id,
        planet_id=planet_id,
        kind=kind,
        max_slots=max_slots,
        reserve_total=reserve,
        emission_rate=base_rate,
    )

    extcall IPlanets(planets).register_node(planet_id, node_id)
    return node_id


@external
@nonreentrant
def set_node_active(node_id: uint256, active: bool):
    """
    @dev Allows or forbids new stakes into `node_id`.
    @notice Only the `owner` can call this function. Existing
            stakes keep earning, and `unstake`/`claim` keep working.
    @param node_id The 32-byte identifier of the node.
    @param active The Boolean variable that sets the status.
    """
    ownable._check_owner()
    self._require_node(node_id)
    self._nodes[node_id].active = active
    log NodeActiveUpdated(node_id=node_id, active=active)


@external
@nonreentrant
def pause():
    """
    @dev Pauses new stakes.
    @notice Only the `owner` can call this function. `unstake` and
            `claim` are not affected.
    """
    ownable._check_owner()
    pausable._pause()


@external
@nonreentrant
def unpause():
    """
    @dev Lifts the pause.
    @notice Only the `owner` can call this function.
    """
    ownable._check_owner()
    pausable._unpause()


@external
@nonreentrant
def stake(node_id: uint256, scv_ids: DynArray[uint256, MAX_SLOTS]):
    """
    @dev Stakes `scv_ids` into `node_id` and escrows them here.
    @notice The caller must own every SCV, every SCV must be
            revealed, and this contract must be approved to move
            them (`approve` or `setApprovalForAll` on the SCV
            contract). The node must be active, not depleted, and
            have enough free slots. Reverts while paused.
            Escrow uses `transferFrom` (not `safeTransferFrom`).
            Before accepting stakes, the function verifies that this
            contract is wired as the SCV stats writer and as the
            MNRL/GAS minter. Both roles are set once and are
            irrevocable, so payouts can never be blocked later.
    @param scv_ids The array of up to `MAX_SLOTS` SCV IDs.
    @param node_id The 32-byte identifier of the node.
    """
    pausable._require_not_paused()
    assert len(scv_ids) != empty(uint256), "mining: empty batch"
    assert staticcall ISCV(scv).mining() == self, "mining: scv not wired"
    assert staticcall IResourceToken(minerals).is_minter(self), "mining: not minter"
    assert staticcall IResourceToken(gas).is_minter(self), "mining: not minter"

    node: IMining.Node = self._update(node_id)
    assert node.active, "mining: node inactive"
    assert node.reserve_remaining != empty(uint256), "mining: node depleted"
    assert convert(node.occupied, uint256) + len(scv_ids) <= convert(node.max_slots, uint256), "mining: node full"

    for scv_id: uint256 in scv_ids:
        assert staticcall IERC721(scv).ownerOf(scv_id) == msg.sender, "mining: not scv owner"
        assert self._positions[scv_id].node_id == empty(uint256), "mining: already staked"
        assert staticcall ISCV(scv).is_revealed(scv_id), "mining: scv not revealed"
        weight: uint256 = staticcall ISCV(scv).mining_weight(scv_id, node.kind)

        self._positions[scv_id] = IMining.Position(
            node_id=node_id,
            owner=msg.sender,
            weight=weight,
            reward_per_weight_paid=node.reward_per_weight_stored,
            accrued=0,
        )
        self._node_scv_index[scv_id] = len(self._node_scvs[node_id])
        self._node_scvs[node_id].append(scv_id)
        assert len(self._staked_by[msg.sender]) < MAX_STAKED_PER_OWNER, "mining: owner stake limit"
        self._staked_by_index[scv_id] = len(self._staked_by[msg.sender])
        self._staked_by[msg.sender].append(scv_id)

        node.total_weight += weight
        node.occupied += 1
        log Staked(owner=msg.sender, node_id=node_id, scv_id=scv_id, weight=weight)

    self._nodes[node_id] = node

    for scv_id: uint256 in scv_ids:
        extcall IERC721(scv).transferFrom(msg.sender, self, scv_id)


@external
@nonreentrant
def unstake(scv_ids: DynArray[uint256, MAX_BATCH]):
    """
    @dev Unstakes `scv_ids`, pays out their rewards, and returns
         them to the caller.
    @notice The caller must be the address that staked each SCV.
            Works while paused, on inactive nodes, and on depleted
            nodes.
    @param scv_ids The array of up to `MAX_BATCH` SCV IDs.
    """
    self._collect(scv_ids, True)


@external
@nonreentrant
def claim(scv_ids: DynArray[uint256, MAX_BATCH]):
    """
    @dev Pays out the rewards of `scv_ids` without unstaking.
    @notice The caller must be the address that staked each SCV.
            Works while paused, on inactive nodes, and on depleted
            nodes.
    @param scv_ids The array of up to `MAX_BATCH` SCV IDs.
    """
    self._collect(scv_ids, False)


@external
def onERC721Received(_operator: address, _from: address, _tokenId: uint256, _data: Bytes[1_024]) -> bytes4:
    """
    @dev Rejects every safe transfer into this contract.
    @notice SCVs must enter escrow through `stake`. A token sent
            via `safeTransferFrom` would have no position and could
            never be recovered (there is no admin rescue function),
            so such transfers revert.
    @param _operator The 20-byte address which called `safeTransferFrom`.
    @param _from The 20-byte address which previously owned the token.
    @param _tokenId The 32-byte identifier of the token.
    @param _data The maximum 1,024-byte additional data.
    @return bytes4 Never returns.
    """
    raise "mining: use stake"


@external
@view
def node(node_id: uint256) -> IMining.Node:
    """
    @dev Returns `node_id`, projected to the current block timestamp
         (i.e. as if the node were updated in this block).
    @notice Throws if `node_id` does not exist.
    @param node_id The 32-byte identifier of the node.
    @return Node The node struct.
    """
    self._require_node(node_id)
    return self._project(self._nodes[node_id])


@external
@view
def position(scv_id: uint256) -> IMining.Position:
    """
    @dev Returns the staking position of `scv_id`.
    @notice Returns an empty struct (`node_id == 0`) if `scv_id`
            is not staked.
    @param scv_id The 32-byte identifier of the SCV.
    @return Position The position struct.
    """
    return self._positions[scv_id]


@external
@view
def pending(scv_id: uint256) -> uint256:
    """
    @dev Returns the rewards that `claim` would pay for `scv_id` now.
    @param scv_id The 32-byte identifier of the SCV.
    @return uint256 The 32-byte claimable amount (0 if not staked).
    """
    return self._pending(scv_id)


@external
@view
def pending_many(scv_ids: DynArray[uint256, MAX_BATCH]) -> DynArray[uint256, MAX_BATCH]:
    """
    @dev Batched version of `pending`.
    @param scv_ids The array of up to `MAX_BATCH` SCV IDs.
    @return DynArray The claimable amounts in the same order.
    """
    amounts: DynArray[uint256, MAX_BATCH] = []
    for scv_id: uint256 in scv_ids:
        amounts.append(self._pending(scv_id))
    return amounts


@external
@view
def node_scvs(node_id: uint256) -> DynArray[uint256, MAX_SLOTS]:
    """
    @dev Returns the SCV IDs staked in `node_id` (unordered).
    @param node_id The 32-byte identifier of the node.
    @return DynArray The array of up to `MAX_SLOTS` SCV IDs.
    """
    return self._node_scvs[node_id]


@external
@view
def staked_by(owner: address) -> DynArray[uint256, MAX_STAKED_PER_OWNER]:
    """
    @dev Returns the SCV IDs staked by `owner` (unordered).
    @param owner The 20-byte owner address.
    @return DynArray The array of up to `MAX_STAKED_PER_OWNER` SCV IDs.
    """
    return self._staked_by[owner]


@external
@view
def is_depleted(node_id: uint256) -> bool:
    """
    @dev Returns whether the reserve of `node_id` is exhausted
         as of the current block timestamp.
    @notice Throws if `node_id` does not exist.
    @param node_id The 32-byte identifier of the node.
    @return bool The verification whether `node_id` is depleted.
    """
    self._require_node(node_id)
    return self._project(self._nodes[node_id]).reserve_remaining == empty(uint256)


@external
@view
def time_to_depletion(node_id: uint256) -> uint256:
    """
    @dev Returns the seconds until `node_id` is depleted at the
         current total weight.
    @notice Returns 0 if depleted, and `max_value(uint256)` if
            nothing is staked (emission is paused). Throws if
            `node_id` does not exist.
    @param node_id The 32-byte identifier of the node.
    @return uint256 The 32-byte number of seconds (rounded up).
    """
    self._require_node(node_id)
    node: IMining.Node = self._project(self._nodes[node_id])
    if node.reserve_remaining == empty(uint256):
        return empty(uint256)
    if node.total_weight == empty(uint256):
        return max_value(uint256)
    return (node.reserve_remaining + node.emission_rate - 1) // node.emission_rate


@internal
@view
def _require_node(node_id: uint256):
    """
    @dev Throws if `node_id` does not exist.
    @param node_id The 32-byte identifier of the node.
    """
    assert node_id != empty(uint256) and node_id <= self.node_count, "mining: unknown node"


@internal
@view
def _project(stored: IMining.Node) -> IMining.Node:
    """
    @dev Returns `stored` advanced to `block.timestamp`.
    @notice Time only counts while `total_weight > 0`. Emission is
            capped by `reserve_remaining`, and the division by
            `total_weight` rounds down, so the sum of all rewards
            never exceeds what was deducted from the reserve.
    @param stored The node as stored.
    @return Node The projected node.
    """
    node: IMining.Node = stored
    now: uint64 = convert(block.timestamp, uint64)
    if node.total_weight != empty(uint256) and node.reserve_remaining != empty(uint256) and now > node.last_update:
        elapsed: uint256 = convert(now - node.last_update, uint256)
        emitted: uint256 = min(node.emission_rate * elapsed, node.reserve_remaining)
        node.reserve_remaining -= emitted
        node.reward_per_weight_stored += emitted * PRECISION // node.total_weight
    node.last_update = now
    return node


@internal
def _update(node_id: uint256) -> IMining.Node:
    """
    @dev Advances `node_id` to `block.timestamp` and stores it.
    @param node_id The 32-byte identifier of the node.
    @return Node The updated node.
    """
    self._require_node(node_id)
    stored: IMining.Node = self._nodes[node_id]
    node: IMining.Node = self._project(stored)
    if stored.reserve_remaining != empty(uint256) and node.reserve_remaining == empty(uint256):
        log NodeDepleted(node_id=node_id)
    self._nodes[node_id] = node
    return node


@internal
@view
def _pending(scv_id: uint256) -> uint256:
    """
    @dev Returns the claimable rewards of `scv_id`.
    @param scv_id The 32-byte identifier of the SCV.
    @return uint256 The 32-byte claimable amount.
    """
    pos: IMining.Position = self._positions[scv_id]
    if pos.node_id == empty(uint256):
        return empty(uint256)
    node: IMining.Node = self._project(self._nodes[pos.node_id])
    return pos.accrued + pos.weight * (node.reward_per_weight_stored - pos.reward_per_weight_paid) // PRECISION


@internal
def _collect(scv_ids: DynArray[uint256, MAX_BATCH], release: bool):
    """
    @dev Settles and pays `scv_ids`, and unstakes them if `release`.
    @notice Follows checks-effects-interactions: all storage writes
            happen before any external call. The external calls only
            target the trusted SCV, MNRL, and GAS contracts.
    @param scv_ids The array of up to `MAX_BATCH` SCV IDs.
    @param release The Boolean variable whether to unstake.
    """
    assert len(scv_ids) != empty(uint256), "mining: empty batch"
    mineral_total: uint256 = empty(uint256)
    gas_total: uint256 = empty(uint256)
    kinds: DynArray[uint8, MAX_BATCH] = []
    rewards: DynArray[uint256, MAX_BATCH] = []

    for scv_id: uint256 in scv_ids:
        pos: IMining.Position = self._positions[scv_id]
        assert pos.node_id != empty(uint256), "mining: not staked"
        assert pos.owner == msg.sender, "mining: not position owner"

        node: IMining.Node = self._update(pos.node_id)
        earned: uint256 = node.reward_per_weight_stored - pos.reward_per_weight_paid
        reward: uint256 = pos.accrued + pos.weight * earned // PRECISION
        self.paid_out[pos.node_id] += reward
        if node.kind == KIND_MINERAL:
            mineral_total += reward
        else:
            gas_total += reward
        kinds.append(node.kind)
        rewards.append(reward)

        if release:
            node.total_weight -= pos.weight
            node.occupied -= 1
            self._nodes[pos.node_id] = node
            self._remove_from_node(pos.node_id, scv_id)
            self._remove_from_owner(msg.sender, scv_id)
            self._positions[scv_id] = empty(IMining.Position)
            log Unstaked(owner=msg.sender, node_id=pos.node_id, scv_id=scv_id, reward=reward)
        else:
            pos.accrued = 0
            pos.reward_per_weight_paid = node.reward_per_weight_stored
            self._positions[scv_id] = pos
            log Claimed(owner=msg.sender, node_id=pos.node_id, scv_id=scv_id, reward=reward)

    idx: uint256 = empty(uint256)
    for scv_id: uint256 in scv_ids:
        if rewards[idx] != empty(uint256):
            extcall ISCV(scv).record_mined(scv_id, kinds[idx], rewards[idx])
        if release:
            extcall IERC721(scv).transferFrom(self, msg.sender, scv_id)
        idx = unsafe_add(idx, 1)

    if mineral_total != empty(uint256):
        extcall IResourceToken(minerals).mint(msg.sender, mineral_total)
    if gas_total != empty(uint256):
        extcall IResourceToken(gas).mint(msg.sender, gas_total)


@internal
def _remove_from_node(node_id: uint256, scv_id: uint256):
    """
    @dev Swap-and-pop removal of `scv_id` from `_node_scvs[node_id]`.
    @param node_id The 32-byte identifier of the node.
    @param scv_id The 32-byte identifier of the SCV.
    """
    index: uint256 = self._node_scv_index[scv_id]
    last_index: uint256 = len(self._node_scvs[node_id]) - 1
    if index != last_index:
        last_id: uint256 = self._node_scvs[node_id][last_index]
        self._node_scvs[node_id][index] = last_id
        self._node_scv_index[last_id] = index
    self._node_scvs[node_id].pop()
    self._node_scv_index[scv_id] = empty(uint256)


@internal
def _remove_from_owner(owner: address, scv_id: uint256):
    """
    @dev Swap-and-pop removal of `scv_id` from `_staked_by[owner]`.
    @param owner The 20-byte owner address.
    @param scv_id The 32-byte identifier of the SCV.
    """
    index: uint256 = self._staked_by_index[scv_id]
    last_index: uint256 = len(self._staked_by[owner]) - 1
    if index != last_index:
        last_id: uint256 = self._staked_by[owner][last_index]
        self._staked_by[owner][index] = last_id
        self._staked_by_index[last_id] = index
    self._staked_by[owner].pop()
    self._staked_by_index[scv_id] = empty(uint256)
