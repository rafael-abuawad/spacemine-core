// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title Spacemine renderer interfaces
/// @notice View-only surface of the Spacemine Vyper contracts, for the web3:// (ERC-4804)
///         renderer that lives in a separate Solidity repository. Struct field order is the
///         ABI tuple order of the Vyper structs and must not be changed independently.
///         `tests/test_solidity_interface.py` checks every selector, return layout, and event
///         here against the compiled Vyper ABIs.
/// @dev Field names are kept in snake_case so they match the Vyper ABI one-to-one.
///      Vyper `flag` values are ABI-encoded as `uint256` bitmasks where member `n` has the
///      value `2**n`; exactly one bit is set for every flag field below (0 = unset).

/// @notice ERC-7572 contract-level metadata, exposed by SCV, Planets, and Spaceships.
interface ISpacemineContractMetadata {
    event ContractURIUpdated();

    function contractURI() external view returns (string memory);

    /// @notice Token-URI prefix, e.g. `web3://0x<renderer>:<chainId>/scv/`.
    function metadata_base() external view returns (string memory);

    /// @notice Token-URI suffix, e.g. `""` or `.json`.
    function metadata_suffix() external view returns (string memory);
}

/// @notice ERC-721 SCV mining bots (`src/scv.vy`).
interface ISCV is ISpacemineContractMetadata {
    /// @param model `Tier` flag: 1 Standard, 2 Advanced, 4 Elite, 8 Prototype (0 = unrevealed).
    /// @param seed  keccak256(blockhash(reveal_block), tokenId, scv); zero for baseline reveals.
    struct SCVProperties {
        bytes32 seed;
        bool revealed;
        uint256 model;
        uint16 mining_power;
        uint16 mineral_efficiency_bps;
        uint16 gas_efficiency_bps;
        uint16 generation;
        uint64 born_at;
    }

    /// @notice ERC-4906.
    event MetadataUpdate(uint256 _tokenId);
    /// @notice ERC-4906. Emitted as (0, type(uint256).max) when the URI scheme changes.
    event BatchMetadataUpdate(uint256 _fromTokenId, uint256 _toTokenId);

    function properties(uint256 tokenId) external view returns (SCVProperties memory);
    function is_revealed(uint256 tokenId) external view returns (bool);
    function reveal_block(uint256 tokenId) external view returns (uint256);
    /// @param kind `ResourceKind` flag: 1 = mineral, 2 = gas. Reverts if the token is not revealed.
    function mining_weight(uint256 tokenId, uint256 kind) external view returns (uint256);
    function lifetime_minerals(uint256 tokenId) external view returns (uint256);
    function lifetime_gas(uint256 tokenId) external view returns (uint256);
    function ownerOf(uint256 tokenId) external view returns (address);
    function totalSupply() external view returns (uint256);
    function total_minted() external view returns (uint256);
    function max_supply() external view returns (uint256);
    function tokenURI(uint256 tokenId) external view returns (string memory);
    function name() external view returns (string memory);
    function symbol() external view returns (string memory);
}

/// @notice Soulbound ERC-721 planets (`src/planets.vy`).
interface IPlanets is ISpacemineContractMetadata {
    /// @param biome `Biome` flag: 1 Terran, 2 Desert, 4 Ice, 8 Volcanic, 16 Ash, 32 Jungle.
    struct Planet {
        string name;
        bytes32 seed;
        uint256 biome;
        uint8 size;
        int32 coord_x;
        int32 coord_y;
        uint16 mineral_richness_bps;
        uint16 gas_richness_bps;
        uint64 created_at;
    }

    /// @notice ERC-5192.
    event Locked(uint256 tokenId);
    event MetadataUpdate(uint256 _tokenId);
    event BatchMetadataUpdate(uint256 _fromTokenId, uint256 _toTokenId);

    function planet(uint256 planetId) external view returns (Planet memory);
    function nodes_of(uint256 planetId) external view returns (uint256[] memory);
    function planet_count() external view returns (uint256);
    function locked(uint256 tokenId) external view returns (bool);
    function ownerOf(uint256 tokenId) external view returns (address);
    function totalSupply() external view returns (uint256);
    function tokenURI(uint256 tokenId) external view returns (string memory);
}

/// @notice Resource nodes and staking (`src/mining.vy`).
interface IMining {
    /// @param kind `ResourceKind` flag: 1 = mineral patch, 2 = gas geyser.
    /// @dev `node()` returns the node projected to `block.timestamp`.
    struct Node {
        uint256 planet_id;
        uint256 kind;
        uint8 max_slots;
        uint8 occupied;
        uint256 reserve_total;
        uint256 reserve_remaining;
        uint256 emission_rate;
        uint256 total_weight;
        uint256 reward_per_weight_stored;
        uint64 last_update;
        bool active;
    }

    /// @dev `node_id == 0` means "not staked".
    struct Position {
        uint256 node_id;
        address owner;
        uint256 weight;
        uint256 reward_per_weight_paid;
        uint256 accrued;
    }

    event Staked(address indexed owner, uint256 indexed node_id, uint256 indexed scv_id, uint256 weight);
    event Unstaked(address indexed owner, uint256 indexed node_id, uint256 indexed scv_id, uint256 reward);
    event Claimed(address indexed owner, uint256 indexed node_id, uint256 indexed scv_id, uint256 reward);
    event NodeDepleted(uint256 indexed node_id);

    function node(uint256 nodeId) external view returns (Node memory);
    function position(uint256 scvId) external view returns (Position memory);
    function pending(uint256 scvId) external view returns (uint256);
    function pending_many(uint256[] calldata scvIds) external view returns (uint256[] memory);
    function is_depleted(uint256 nodeId) external view returns (bool);
    function time_to_depletion(uint256 nodeId) external view returns (uint256);
    function node_scvs(uint256 nodeId) external view returns (uint256[] memory);
    function staked_by(address owner) external view returns (uint256[] memory);
    function node_count() external view returns (uint256);
    function paid_out(uint256 nodeId) external view returns (uint256);
}

/// @notice ERC-1155 ship types (`src/spaceships.vy`).
interface ISpaceships is ISpacemineContractMetadata {
    /// @param ship_class `ShipClass` flag: 1 Fighter, 2 Frigate, 4 Freighter, 8 Cruiser, 16 Carrier.
    /// @param max_supply 0 = unlimited.
    struct ShipType {
        string name;
        uint256 ship_class;
        uint256 mineral_cost;
        uint256 gas_cost;
        uint256 max_supply;
        uint256 minted;
        bool active;
        uint16 hull;
        uint16 shield;
        uint16 attack;
        uint16 speed;
        uint32 cargo;
        uint64 created_at;
    }

    /// @notice ERC-1155 metadata refresh, emitted per type on creation and on URI scheme changes.
    event URI(string _value, uint256 indexed _id);

    function ship_type(uint256 shipId) external view returns (ShipType memory);
    function ship_type_count() external view returns (uint256);
    /// @notice Circulating supply (decreases on burn). `ShipType.minted` never decreases.
    function total_supply(uint256 shipId) external view returns (uint256);
    function exists(uint256 shipId) external view returns (bool);
    function quote(uint256 shipId, uint256 amount) external view returns (uint256 mineralCost, uint256 gasCost);
    function balanceOf(address owner, uint256 shipId) external view returns (uint256);
    function uri(uint256 shipId) external view returns (string memory);
}
