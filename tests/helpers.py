"""Shared constants and helpers for the Spacemine test-suite."""

from pathlib import Path

import boa

ROOT = Path(__file__).resolve().parent.parent
MOCKS = ROOT / "tests" / "mocks"

E18 = 10**18
MAX_UINT256 = 2**256 - 1
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
DEAD_ADDRESS = "0x000000000000000000000000000000000000dEaD"

# Vyper `flag` values: member `n` encodes as `2**n` (ABI type `uint256`).
KIND_MINERAL, KIND_GAS = 1, 2  # ISCV.ResourceKind
STANDARD, ADVANCED, ELITE, PROTOTYPE = 1, 2, 4, 8  # ISCV.Tier
TERRAN, DESERT, ICE, VOLCANIC, ASH, JUNGLE = 1, 2, 4, 8, 16, 32  # IPlanets.Biome
FIGHTER, FRIGATE, FREIGHTER, CRUISER, CARRIER = 1, 2, 4, 8, 16  # spaceships.ShipClass
SCV_PRICE = 100 * E18
PRECISION = 10**18
RENDERER = "0x1111111111111111111111111111111111111111"

# EIP-2935 history contract. `scv` deliberately never queries it (see `scv.vy` @notice).
HISTORY_ADDRESS = "0x0000F90827F1C53a10cb7A02335B175320002935"
HISTORY_CODE = bytes.fromhex(
    "3373fffffffffffffffffffffffffffffffffffffffe14604657602036036042575f35600143038111604257"
    "611fff81430311604257611fff9006545f5260205ff35b5f5ffd5b5f35611fff60014303065500"
)

# SCV roll tables (mirror `SCV._roll`).
TIER_THRESHOLDS = [6_000, 8_500, 9_700, 10_000]
TIER_POWER = [(100, 149), (150, 219), (220, 299), (300, 400)]

SCV_BASE = f"web3://{RENDERER}:1/scv/"
PLANETS_BASE = f"web3://{RENDERER}:1/planets/"
SHIPS_BASE = f"web3://{RENDERER}:1/ships/"


def load_mock(name: str, *args):
    return boa.load_partial(str(MOCKS / f"{name}.vy")).deploy(*args)


def event_names(contract) -> list[str]:
    return [type(log).__name__ for log in contract.get_logs()]


def events(contract, name: str) -> list:
    return [log for log in contract.get_logs() if type(log).__name__ == name]


def expected_roll(seed: bytes) -> tuple[int, int, int, int]:
    """Python mirror of `scv._roll`: (model flag, mining_power, mineral_bps, gas_bps)."""
    rand = int.from_bytes(seed, "big")
    tier = next(i for i, threshold in enumerate(TIER_THRESHOLDS) if rand % 10_000 < threshold)
    low, high = TIER_POWER[tier]
    power = low + (rand >> 64) % (high - low + 1)
    mineral = 5_000 + (rand >> 128) % 10_001
    gas = 5_000 + (rand >> 192) % 10_001
    return 1 << tier, power, mineral, gas


def set_block_hash(target_block: int, block_hash: bytes):
    """Plant the native `blockhash(target_block)` (must be within the last 256 blocks)."""
    offset = block_number() - 1 - target_block
    assert 0 <= offset < 256, "target outside the native blockhash window"
    hashes = list(boa.env.evm.patch.prev_hashes) + [b"\x00" * 32] * 256
    hashes = hashes[:256]
    hashes[offset] = block_hash
    boa.env.evm.patch.prev_hashes = hashes


def log_args(log) -> tuple:
    """Event arguments without the emitting address (works for `_`-prefixed field names)."""
    return tuple(log)[1:]


def block_number() -> int:
    return boa.env.evm.patch.block_number


def fund_credits(world, user, amount: int, approve: bool = True):
    world.credits.mint(user, amount)
    if approve:
        world.credits.approve(world.scv.address, amount, sender=user)


def buy_scvs(world, user, quantity: int) -> list[int]:
    cost = world.scv.price() * quantity
    fund_credits(world, user, cost)
    first = world.scv.buy(quantity, cost, sender=user)
    return list(range(first, first + quantity))


def reveal_now(world, token_ids: list[int]):
    """Advance past the reveal block of `token_ids` (which must share a commit block) and reveal."""
    target = world.scv.reveal_block(token_ids[0])
    if block_number() <= target:
        boa.env.time_travel(blocks=target + 1 - block_number())
    world.scv.reveal(token_ids)


def buy_and_reveal(world, user, quantity: int) -> list[int]:
    ids = buy_scvs(world, user, quantity)
    reveal_now(world, ids)
    return ids


def stake(world, user, node_id: int, ids: list[int]):
    world.scv.setApprovalForAll(world.mining.address, True, sender=user)
    world.mining.stake(node_id, ids, sender=user)


def give_resources(world, user, minerals: int = 0, gas: int = 0, approve: bool = True):
    """Test shortcut: mint resources by pranking the Mining contract (the only minter)."""
    if minerals:
        world.minerals.mint(user, minerals, sender=world.mining.address)
        if approve:
            world.minerals.approve(world.spaceships.address, minerals, sender=user)
    if gas:
        world.gas.mint(user, gas, sender=world.mining.address)
        if approve:
            world.gas.approve(world.spaceships.address, gas, sender=user)


def weight_of(world, scv_id: int, kind: int) -> int:
    return world.scv.mining_weight(scv_id, kind)


def now() -> int:
    return boa.env.evm.patch.timestamp


class NodeModel:
    """Pure-Python reference model of one Mining node (mirrors `_project` / `_collect`)."""

    def __init__(self, reserve: int, rate: int, created_at: int):
        self.reserve_total = reserve
        self.reserve_remaining = reserve
        self.rate = rate
        self.rpw = 0
        self.total_weight = 0
        self.last = created_at
        self.positions: dict[int, list[int]] = {}  # scv_id -> [weight, rpw_paid]
        self.paid = 0

    def update(self, timestamp: int):
        if self.total_weight and self.reserve_remaining and timestamp > self.last:
            emitted = min(self.rate * (timestamp - self.last), self.reserve_remaining)
            self.reserve_remaining -= emitted
            self.rpw += emitted * PRECISION // self.total_weight
        self.last = timestamp

    def stake(self, scv_id: int, weight: int, timestamp: int):
        self.update(timestamp)
        self.positions[scv_id] = [weight, self.rpw]
        self.total_weight += weight

    def pending(self, scv_id: int, timestamp: int) -> int:
        snapshot = (self.reserve_remaining, self.rpw, self.last)
        self.update(timestamp)
        weight, paid = self.positions[scv_id]
        reward = weight * (self.rpw - paid) // PRECISION
        self.reserve_remaining, self.rpw, self.last = snapshot
        return reward

    def collect(self, scv_id: int, timestamp: int, release: bool) -> int:
        self.update(timestamp)
        weight, paid = self.positions[scv_id]
        reward = weight * (self.rpw - paid) // PRECISION
        self.paid += reward
        if release:
            del self.positions[scv_id]
            self.total_weight -= weight
        else:
            self.positions[scv_id][1] = self.rpw
        return reward
