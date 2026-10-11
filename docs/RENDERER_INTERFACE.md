# Spacemine renderer interface

This document is the contract between the Spacemine Vyper contracts (this repository) and the
**web3:// (ERC-4804) renderer**, which is built in a separate Solidity repository. The renderer
builds JSON and SVG metadata **using only view calls**. The Vyper contracts store and concatenate
URI strings; they never parse them.

The Solidity side of this interface is [`interfaces/solidity/ISpacemine.sol`](../interfaces/solidity/ISpacemine.sol).
`tests/test_solidity_interface.py` compiles it with `solc` and checks every function selector,
return type, struct field order and name, and event signature against the compiled Vyper ABIs.
If you change a struct in Vyper, that test fails until the `.sol` file is updated too.

## 1. URI shapes

All three collections use the same scheme (`src/modules/metadata.vy`):

```
tokenURI(id) / uri(id) = metadata_base || decimal(id) || metadata_suffix
contractURI()          = opaque string (ERC-7572)
```

| Getter | Bound | Example (deploy-script default) |
|---|---|---|
| `metadata_base()` | 160 chars | `web3://0x<renderer>:<chainId>/scv/` |
| `metadata_suffix()` | 32 chars | `""` (or `.json`) |
| `SCV.tokenURI(7)` | 270 chars (declared `string`) | `web3://0x<renderer>:<chainId>/scv/7` |
| `Planets.tokenURI(1)` | 270 chars | `web3://0x<renderer>:<chainId>/planets/1` |
| `Spaceships.uri(3)` | 270 chars | `web3://0x<renderer>:<chainId>/ships/3` |
| `contractURI()` | 256 chars | `web3://0x<renderer>:<chainId>/scv/contract` |

Notes:

- The ERC-1155 `uri(id)` contains the **literal** ID and no `{id}` placeholder, because
  web3:// resolution needs the concrete ID.
- `tokenURI`/`uri` revert for tokens or ship types that don't exist
  (`erc721: invalid token ID`, `spaceships: unknown ship type`).
- IDs are 1-based and sequential in every collection (SCV, planet, node, ship type).
- In ERC-4804 terms the renderer is expected to use auto-mode or a manual resolver that
  routes `/scv/<id>`, `/planets/<id>`, `/ships/<id>` and `/<collection>/contract`. The Vyper
  contracts don't care: the owner can switch the base or suffix at any time
  (`set_metadata_uri`, `set_contract_uri`).

## 2. View calls by collection

### `ISCV` (`src/scv.vy`, ERC-721)

| Call | Returns | Notes |
|---|---|---|
| `properties(uint256)` | `SCVProperties` tuple | reverts if the token doesn't exist |
| `is_revealed(uint256)` | `bool` | `false` for non-existent tokens |
| `reveal_block(uint256)` | `uint256` | commit block; reveal is possible once `block.number > reveal_block` |
| `mining_weight(uint256 id, uint256 kind)` | `uint256` | `mining_power * efficiency_bps(kind) / 10_000`; reverts if unrevealed |
| `lifetime_minerals(uint256)` / `lifetime_gas(uint256)` | `uint256` | resource wei mined, all-time |
| `ownerOf(uint256)` | `address` | equals the Mining address while staked |
| `totalSupply()` / `total_minted()` / `max_supply()` | `uint256` | there is no burn, so `totalSupply == total_minted` |

```solidity
struct SCVProperties {      // ABI tuple order, do not reorder
    bytes32 seed;           // keccak256(abi.encode(blockhash(reveal_block), tokenId, scv)); 0x0 = baseline reveal
    bool    revealed;
    uint256 model;          // `Tier` flag, see section 4 (0 before reveal)
    uint16  mining_power;   // 100..400
    uint16  mineral_efficiency_bps; // 5_000..15_000
    uint16  gas_efficiency_bps;     // 5_000..15_000
    uint16  generation;     // sale batch, stamped at mint
    uint64  born_at;        // mint timestamp
}
```

Before reveal, only `generation` and `born_at` are set; everything else is zero. Render these
tokens as "unrevealed".

### `IPlanets` (`src/planets.vy`, soulbound ERC-721 / ERC-5192)

| Call | Returns | Notes |
|---|---|---|
| `planet(uint256)` | `Planet` tuple | reverts if the planet doesn't exist |
| `nodes_of(uint256)` | `uint256[]` (max 16) | node IDs in creation order |
| `planet_count()` / `totalSupply()` | `uint256` | |
| `ownerOf(uint256)` | `address` | always the Planets contract itself |
| `locked(uint256)` | `bool` | always `true` |

```solidity
struct Planet {
    string  name;                 // max 32 chars
    bytes32 seed;                 // cosmetic, deterministic
    uint256 biome;                // `Biome` flag, see section 4
    uint8   size;                 // 1..10
    int32   coord_x;
    int32   coord_y;
    uint16  mineral_richness_bps; // 0..30_000; scales node reserves
    uint16  gas_richness_bps;     // 0..30_000
    uint64  created_at;
}
```

### `IMining` (`src/mining.vy`)

| Call | Returns | Notes |
|---|---|---|
| `node(uint256)` | `Node` tuple | **projected to `block.timestamp`**: `reserve_remaining`, `reward_per_weight_stored`, and `last_update` are what they would be if the node were updated in this block |
| `position(uint256 scvId)` | `Position` tuple | `node_id == 0` means not staked |
| `pending(uint256 scvId)` | `uint256` | claimable resource wei right now |
| `pending_many(uint256[])` | `uint256[]` | max 32 IDs |
| `is_depleted(uint256)` | `bool` | |
| `time_to_depletion(uint256)` | `uint256` | seconds, rounded up; `0` if depleted, `type(uint256).max` if nothing is staked |
| `node_scvs(uint256)` | `uint256[]` (max 8) | unordered |
| `staked_by(address)` | `uint256[]` (max 128) | unordered |
| `node_count()` / `paid_out(uint256)` | `uint256` | `paid_out` = resources minted by that node so far |

```solidity
struct Node {
    uint256 planet_id;
    uint256 kind;                   // `ResourceKind` flag: 1 mineral patch, 2 gas geyser
    uint8   max_slots;              // 1..8
    uint8   occupied;
    uint256 reserve_total;          // resource wei, already scaled by planet richness
    uint256 reserve_remaining;
    uint256 emission_rate;          // resource wei per second, shared pro rata by weight
    uint256 total_weight;
    uint256 reward_per_weight_stored; // 1e18 fixed point
    uint64  last_update;
    bool    active;                 // false = no new stakes (exits still work)
}

struct Position {
    uint256 node_id;
    address owner;                  // the address the SCV is returned to
    uint256 weight;
    uint256 reward_per_weight_paid;
    uint256 accrued;                // settled-but-unpaid rewards (always 0 in v1: settlements pay out immediately)
}
```

### `ISpaceships` (`src/spaceships.vy`, ERC-1155)

| Call | Returns | Notes |
|---|---|---|
| `ship_type(uint256)` | `ShipType` tuple | reverts if the ship type doesn't exist |
| `ship_type_count()` | `uint256` | max 64 |
| `total_supply(uint256)` | `uint256` | circulating (drops on burn). snekmate names it `total_supply`, not `totalSupply` |
| `exists(uint256)` | `bool` | snekmate semantics: `total_supply(id) > 0`, **not** "type registered" |
| `quote(uint256 id, uint256 amount)` | `(uint256 mineral, uint256 gas)` | current price × amount |
| `balanceOf(address, uint256)` | `uint256` | |

```solidity
struct ShipType {
    string  name;          // max 32 chars
    uint256 ship_class;    // `ShipClass` flag, see section 4 (`class` is reserved in Vyper)
    uint256 mineral_cost;  // MNRL wei per ship (mutable by owner)
    uint256 gas_cost;      // GAS wei per ship (mutable by owner)
    uint256 max_supply;    // 0 = unlimited; can only decrease
    uint256 minted;        // lifetime minted; never decreases on burn
    bool    active;
    uint16  hull;          // stats below are immutable after creation
    uint16  shield;
    uint16  attack;
    uint16  speed;
    uint32  cargo;
    uint64  created_at;
}
```

## 3. Refresh events

| Event | Emitted by | When | Renderer / indexer action |
|---|---|---|---|
| `MetadataUpdate(uint256 _tokenId)` (ERC-4906) | SCV | reveal; lifetime stats change (claim/unstake) | refetch that SCV |
| `MetadataUpdate(uint256 _tokenId)` (ERC-4906) | Planets | a node is registered on the planet | refetch that planet |
| `BatchMetadataUpdate(0, type(uint256).max)` (ERC-4906) | SCV, Planets | `set_metadata_uri` | refetch the whole collection |
| `URI(string _value, uint256 indexed _id)` (ERC-1155) | Spaceships | type creation, and once per existing type on `set_metadata_uri` | refetch that type |
| `ContractURIUpdated()` (ERC-7572) | SCV, Planets, Spaceships | `set_contract_uri` and at construction if a URI was given | refetch contract metadata |
| `Transfer` (ERC-721) | SCV | stake (owner → Mining) and unstake (Mining → owner) | staking status changed |
| `Staked` / `Unstaked` / `Claimed` / `NodeDepleted` | Mining | position or node changes | refresh node and planet views |

Time-dependent values (`pending`, `reserve_remaining`, `time_to_depletion`) change every second
without an event, so render them at read time and don't cache them.

## 4. Flag values

The Vyper contracts use [`flag`](https://docs.vyperlang.org/en/stable/types.html#flags) types.
A flag is ABI-encoded as a `uint256` bitmask in which member `n` has the value `2**n`.
Every flag field holds **exactly one** member; the contracts reject the empty value and
combinations of members on input. Decode with `value == 1 << n`, not `value == n`.

**SCV `model`** (`ISCV.Tier`; `0` means "not revealed yet")

| Value | Member | Probability | `mining_power` |
|---|---|---|---|
| 1 | `STANDARD` | 60% | 100–149 |
| 2 | `ADVANCED` | 25% | 150–219 |
| 4 | `ELITE` | 12% | 220–299 |
| 8 | `PROTOTYPE` | 3% | 300–400 |

Efficiencies are uniform in 5,000–15,000 bps and independent of the tier. **Baseline reveal**
(the reveal came more than 256 blocks after the commit block): `seed = 0x0`, `model = 1` (`STANDARD`), `mining_power = 100`, both
efficiencies `5,000`. This is the worst possible roll, so you may want to render it as
"Salvaged" or similar.

**Planet `biome`** (`IPlanets.Biome`): 1 `TERRAN`, 2 `DESERT`, 4 `ICE`, 8 `VOLCANIC`, 16 `ASH`, 32 `JUNGLE`.

**Node `kind`** (`ISCV.ResourceKind`): 1 `MINERAL` (patch, pays MNRL), 2 `GAS` (geyser, pays GAS).

**Ship `ship_class`** (`spaceships.ShipClass`): 1 `FIGHTER`, 2 `FRIGATE`, 4 `FREIGHTER`, 8 `CRUISER`, 16 `CARRIER`.

**Resource amounts**: MNRL and GAS have 18 decimals; all costs, reserves, rates and rewards are in wei.
