# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Spacemine Planets Collection
@custom:contract-name planets
@license MIT
@notice ERC-721 collection of worlds that nobody owns. Every planet
        is minted to this contract itself and can never move. It is
        soulbound as per ERC-5192 (https://eips.ethereum.org/EIPS/eip-5192):
        `locked` always returns `True` and `Locked` is emitted at mint.
        Only the read-side `erc721` functions are exported from the
        snekmate module. ERC-5192 requires the token to be a full
        ERC-721, so `transferFrom`, `safeTransferFrom`, `approve`, and
        `setApprovalForAll` are implemented here as functions that
        always revert (instead of being absent). This keeps
        `implements: IERC721` and the advertised ERC-721 interface ID
        truthful while making every transfer or approval impossible.
        `burn`, `permit`, `safe_mint`, and `set_minter` are not exposed.
        Every resource node of `Mining` belongs to exactly one planet
        and is registered here by the wired `Mining` contract.
"""


# @dev We import and implement the `IERC165` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC165
implements: IERC165


# @dev We import and implement the `IERC721` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC721
implements: IERC721


# @dev We import and implement the snekmate interfaces
# for the ERC-721 extensions that this contract exposes.
from snekmate.tokens.interfaces import IERC721Metadata
implements: IERC721Metadata


from snekmate.tokens.interfaces import IERC721Enumerable
implements: IERC721Enumerable


from snekmate.tokens.interfaces import IERC4906
implements: IERC4906


# @dev We import and implement the project-specific
# `IPlanets` interface (which also defines `Planet`).
from .interfaces import IPlanets
implements: IPlanets


# @dev We import and initialise the `ownable` module and
# use the two-step ownership transfer of `ownable_2step`.
from snekmate.auth import ownable
initializes: ownable
from snekmate.auth import ownable_2step
initializes: ownable_2step[ownable := ownable]


# @dev We import and initialise the `erc721` module.
from snekmate.tokens import erc721
initializes: erc721[ownable := ownable]


# @dev We import and initialise the shared metadata module.
from .modules import metadata
initializes: metadata


# @dev We export only the read-side `erc721` functions.
exports: (
    erc721.balanceOf,
    erc721.ownerOf,
    erc721.getApproved,
    erc721.isApprovedForAll,
    erc721.name,
    erc721.symbol,
    erc721.totalSupply,
    erc721.tokenByIndex,
    erc721.tokenOfOwnerByIndex,
    ownable.owner,
    ownable_2step.pending_owner,
    ownable_2step.transfer_ownership,
    ownable_2step.accept_ownership,
    ownable_2step.renounce_ownership,
    metadata.metadata_base,
    metadata.metadata_suffix,
    metadata.contractURI,
)


# @dev Stores the ERC-165 interface identifiers of exactly
# the exposed surface. ERC-4494 (`permit`) and ERC-2981
# (royalties) are deliberately absent.
_SUPPORTED_INTERFACES: constant(bytes4[6]) = [
    0x01FFC9A7, # The ERC-165 identifier for ERC-165.
    0x80AC58CD, # The ERC-165 identifier for ERC-721.
    0x5B5E139F, # The ERC-165 identifier for the ERC-721 metadata extension.
    0x780E9D63, # The ERC-165 identifier for the ERC-721 enumeration extension.
    0x49064906, # The ERC-165 identifier for ERC-4906.
    0xB45A3C0E, # The ERC-165 identifier for ERC-5192.
]


# @dev The maximum number of resource nodes per planet.
MAX_NODES_PER_PLANET: public(constant(uint256)) = 16


# @dev The inclusive bounds for `size`.
MIN_SIZE: public(constant(uint8)) = 1
MAX_SIZE: public(constant(uint8)) = 10


# @dev The upper bound for the richness multipliers (3x).
MAX_RICHNESS_BPS: public(constant(uint16)) = 30_000


# @dev Returns the number of planets created so far (IDs are
# 1-based and sequential).
planet_count: public(uint256)


# @dev Returns the `Mining` contract allowed to register nodes.
mining: public(address)


# @dev Mapping from planet ID to its properties.
_planets: HashMap[uint256, IPlanets.Planet]


# @dev Mapping from planet ID to its resource node IDs.
_nodes: HashMap[uint256, DynArray[uint256, MAX_NODES_PER_PLANET]]


# @dev Emitted when a token is locked (ERC-5192).
event Locked:
    tokenId: uint256


# @dev Emitted when a planet is created.
event PlanetCreated:
    planet_id: indexed(uint256)
    name: String[32]
    biome: IPlanets.Biome
    size: uint8
    coord_x: int32
    coord_y: int32
    mineral_richness_bps: uint16
    gas_richness_bps: uint16


# @dev Emitted when a resource node is registered on a planet.
event NodeRegistered:
    planet_id: indexed(uint256)
    node_id: indexed(uint256)


# @dev Emitted once, when the `Mining` contract is wired.
event MiningSet:
    mining: indexed(address)


@deploy
@payable
def __init__(metadata_base_: String[160], metadata_suffix_: String[32], contract_uri_: String[256]):
    """
    @dev To omit the opcodes for checking the `msg.value`
         in the creation-time EVM bytecode, the constructor
         is declared as `payable`.
    @notice The `owner` role is assigned to `msg.sender`. The
            unused `erc721` minter role is revoked right away.
    @param metadata_base_ The maximum 160-character token-URI prefix.
    @param metadata_suffix_ The maximum 32-character token-URI suffix.
    @param contract_uri_ The maximum 256-character ERC-7572 contract URI.
    """
    ownable.__init__()
    ownable_2step.__init__()
    erc721.__init__("Spacemine Planets", "PLNT", "", "Spacemine Planets", "1")
    metadata.__init__(metadata_base_, metadata_suffix_, contract_uri_)

    erc721.is_minter[msg.sender] = False
    log erc721.RoleMinterChanged(minter=msg.sender, status=False)


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
@payable
def transferFrom(owner: address, to: address, token_id: uint256):
    """
    @dev Always reverts: planets are soulbound (ERC-5192).
    @notice The function is declared as `payable` to comply
            with the EIP-721 standard definition.
    @param owner The 20-byte owner address.
    @param to The 20-byte receiver address.
    @param token_id The 32-byte identifier of the token.
    """
    raise "planets: soulbound"


@external
@payable
def safeTransferFrom(owner: address, to: address, token_id: uint256, data: Bytes[1_024] = b""):
    """
    @dev Always reverts: planets are soulbound (ERC-5192).
    @notice The function is declared as `payable` to comply
            with the EIP-721 standard definition. Both the
            3- and 4-argument selectors are covered.
    @param owner The 20-byte owner address.
    @param to The 20-byte receiver address.
    @param token_id The 32-byte identifier of the token.
    @param data The maximum 1,024-byte additional data.
    """
    raise "planets: soulbound"


@external
@payable
def approve(to: address, token_id: uint256):
    """
    @dev Always reverts: planets are soulbound (ERC-5192).
    @notice The function is declared as `payable` to comply
            with the EIP-721 standard definition.
    @param to The 20-byte spender address.
    @param token_id The 32-byte identifier of the token.
    """
    raise "planets: soulbound"


@external
def setApprovalForAll(operator: address, approved: bool):
    """
    @dev Always reverts: planets are soulbound (ERC-5192).
    @param operator The 20-byte operator address.
    @param approved The Boolean variable that sets the
           approval status.
    """
    raise "planets: soulbound"


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
@view
def locked(token_id: uint256) -> bool:
    """
    @dev Returns the locking status of `token_id` (ERC-5192).
    @notice Throws if `token_id` does not exist. Planets are
            always locked.
    @param token_id The 32-byte identifier of the token.
    @return bool Always `True`.
    """
    erc721._require_minted(token_id)
    return True


@external
def create_planet(
    name: String[32],
    biome: IPlanets.Biome,
    size: uint8,
    coord_x: int32,
    coord_y: int32,
    mineral_richness_bps: uint16,
    gas_richness_bps: uint16,
) -> uint256:
    """
    @dev Creates a planet and mints its token to this contract.
    @notice Only the `owner` can call this function. All properties
            are immutable after creation. The `seed` is derived
            deterministically and is cosmetic (renderer input only).
            A richness of 0 means the planet can host no node of
            that kind.
    @param name The maximum 32-character non-empty planet name.
    @param biome The `IPlanets.Biome` (exactly one member).
    @param size The 1-byte size (`MIN_SIZE`..`MAX_SIZE`).
    @param coord_x The 4-byte signed x coordinate.
    @param coord_y The 4-byte signed y coordinate.
    @param mineral_richness_bps The 2-byte mineral reserve multiplier
           in basis points (0..`MAX_RICHNESS_BPS`).
    @param gas_richness_bps The 2-byte gas reserve multiplier in
           basis points (0..`MAX_RICHNESS_BPS`).
    @return uint256 The 32-byte ID of the new planet.
    """
    ownable._check_owner()
    assert len(name) != empty(uint256), "planets: empty name"
    # Out-of-range flag values are rejected by the ABI decoder; this
    # rejects the empty flag and combinations of several biomes.
    biome_bits: uint256 = convert(biome, uint256)
    assert biome_bits != empty(uint256) and biome_bits & (biome_bits - 1) == empty(uint256), "planets: invalid biome"
    assert size >= MIN_SIZE and size <= MAX_SIZE, "planets: invalid size"
    assert mineral_richness_bps <= MAX_RICHNESS_BPS, "planets: invalid richness"
    assert gas_richness_bps <= MAX_RICHNESS_BPS, "planets: invalid richness"

    planet_id: uint256 = self.planet_count + 1
    self.planet_count = planet_id
    self._planets[planet_id] = IPlanets.Planet(
        name=name,
        seed=keccak256(abi_encode(self, planet_id, name, coord_x, coord_y, block.timestamp)),
        biome=biome,
        size=size,
        coord_x=coord_x,
        coord_y=coord_y,
        mineral_richness_bps=mineral_richness_bps,
        gas_richness_bps=gas_richness_bps,
        created_at=convert(block.timestamp, uint64),
    )
    erc721._mint(self, planet_id)
    log Locked(tokenId=planet_id)
    log PlanetCreated(
        planet_id=planet_id,
        name=name,
        biome=biome,
        size=size,
        coord_x=coord_x,
        coord_y=coord_y,
        mineral_richness_bps=mineral_richness_bps,
        gas_richness_bps=gas_richness_bps,
    )
    return planet_id


@external
def register_node(planet_id: uint256, node_id: uint256):
    """
    @dev Appends `node_id` to the node registry of `planet_id`.
    @notice Only the wired `Mining` contract can call this function.
    @param planet_id The 32-byte identifier of the planet.
    @param node_id The 32-byte identifier of the node.
    """
    assert msg.sender == self.mining, "planets: caller is not mining"
    erc721._require_minted(planet_id)
    assert len(self._nodes[planet_id]) < MAX_NODES_PER_PLANET, "planets: node limit reached"
    self._nodes[planet_id].append(node_id)
    log NodeRegistered(planet_id=planet_id, node_id=node_id)
    log IERC4906.MetadataUpdate(_tokenId=planet_id)


@external
@view
def planet(planet_id: uint256) -> IPlanets.Planet:
    """
    @dev Returns the properties of `planet_id`.
    @notice Throws if `planet_id` does not exist.
    @param planet_id The 32-byte identifier of the planet.
    @return Planet The planet struct.
    """
    erc721._require_minted(planet_id)
    return self._planets[planet_id]


@external
@view
def nodes_of(planet_id: uint256) -> DynArray[uint256, MAX_NODES_PER_PLANET]:
    """
    @dev Returns the resource node IDs registered on `planet_id`.
    @param planet_id The 32-byte identifier of the planet.
    @return DynArray The array of up to 16 node IDs.
    """
    return self._nodes[planet_id]


@external
def set_mining(mining_: address):
    """
    @dev Wires the `Mining` contract that may register nodes.
    @notice Only the `owner` can call this function, and only once.
    @param mining_ The 20-byte `Mining` address.
    """
    ownable._check_owner()
    assert self.mining == empty(address), "planets: mining already set"
    assert mining_ != empty(address), "planets: mining is the zero address"
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
