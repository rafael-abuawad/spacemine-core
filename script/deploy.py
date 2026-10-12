"""Deploy and wire the Spacemine contract suite.

Usage:
    mox run deploy                       # local pyevm, with mock CREDITS and demo seed
    mox run deploy --network <name>      # live network, CREDITS_ADDRESS required

Configuration (environment variables, all optional unless noted):
    CREDITS_ADDRESS       CREDITS ERC-20 address (required on live networks)
    TREASURY_ADDRESS      CREDITS / ship-payment treasury (default: deployer)
    SCV_BURN_PROCEEDS     "1" to send CREDITS to 0x...dEaD instead of the treasury
    SCV_PRICE             SCV price in CREDITS base units (default: 100e18)
    SCV_MAX_SUPPLY        SCV max supply (default: 10_000)
    RENDERER_ADDRESS      web3:// renderer contract (default: zero-address placeholder)
    METADATA_SUFFIX       token-URI suffix (default: "")
    SCV_BASE_URI / PLANETS_BASE_URI / SHIPS_BASE_URI           override token-URI prefixes
    SCV_CONTRACT_URI / PLANETS_CONTRACT_URI / SHIPS_CONTRACT_URI  override contract URIs
    ROYALTY_BPS           default ERC-2981 royalty for SCV and Spaceships (default: 500)
    SEED_DEMO             "1"/"0" to force or skip the demo seed (default: local networks only)
    SEED_FILE             demo universe JSON (default: script/demo_seed.json)
"""

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import boa
from moccasin.boa_tools import VyperContract
from moccasin.config import get_active_network

from src import mining as Mining
from src import planets as Planets
from src import resource_token as ResourceToken
from src import scv as SCV
from src import spaceships as Spaceships

ROOT = Path(__file__).resolve().parent.parent
MOCKS = ROOT / "tests" / "mocks"
DEMO_SEED = ROOT / "script" / "demo_seed.json"

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
# Vyper `flag` values (member `n` encodes as `2**n`).
KINDS = {"MINERAL": 1, "GAS": 2}
BIOMES = {"TERRAN": 1, "DESERT": 2, "ICE": 4, "VOLCANIC": 8, "ASH": 16, "JUNGLE": 32}
SHIP_CLASSES = {"FIGHTER": 1, "FRIGATE": 2, "FREIGHTER": 4, "CRUISER": 8, "CARRIER": 16}
E18 = 10**18


def _fn(name, inputs, outputs, mutability):
    return {
        "type": "function",
        "name": name,
        "stateMutability": mutability,
        "inputs": [{"name": n, "type": t} for n, t in inputs],
        "outputs": [{"name": "", "type": t} for t in outputs],
    }


# Minimal ERC-20 ABI used to attach to the external CREDITS token.
ERC20_ABI = [
    _fn("balanceOf", [("owner", "address")], ["uint256"], "view"),
    _fn("allowance", [("owner", "address"), ("spender", "address")], ["uint256"], "view"),
    _fn("totalSupply", [], ["uint256"], "view"),
    _fn("decimals", [], ["uint8"], "view"),
    _fn("approve", [("spender", "address"), ("amount", "uint256")], ["bool"], "nonpayable"),
]


@dataclass
class Spacemine:
    credits: VyperContract
    scv: VyperContract
    planets: VyperContract
    minerals: VyperContract
    gas: VyperContract
    mining: VyperContract
    spaceships: VyperContract
    treasury: str


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _chain_id() -> int:
    network = get_active_network()
    if network.chain_id:
        return int(network.chain_id)
    return int(boa.env.evm.patch.chain_id)


def _is_local() -> bool:
    return get_active_network().is_local_or_forked_network()


def deploy_mock_credits() -> VyperContract:
    """Deploy the test-only CREDITS mock (never used on live networks)."""
    return boa.load_partial(str(MOCKS / "mock_credits.vy")).deploy()


def deploy(
    credits_address: str | None = None,
    treasury: str | None = None,
    burn_proceeds: bool | None = None,
    seed_demo: bool | None = None,
    verbose: bool = False,
) -> Spacemine:
    """Deploy all contracts, wire roles, set metadata, and optionally seed demo content."""
    deployer = str(boa.env.eoa)
    local = _is_local()
    chain_id = _chain_id()

    # 1. CREDITS: mock locally, external address on live networks.
    credits_address = credits_address or os.environ.get("CREDITS_ADDRESS")
    if credits_address:
        credits = boa.loads_abi(json.dumps(ERC20_ABI), name="CREDITS").at(credits_address)
    elif local:
        credits = deploy_mock_credits()
    else:
        raise ValueError("CREDITS_ADDRESS must be set on live networks")

    treasury = treasury or _env("TREASURY_ADDRESS", deployer)
    if burn_proceeds is None:
        burn_proceeds = _env("SCV_BURN_PROCEEDS", "0") == "1"
    price = int(_env("SCV_PRICE", str(100 * E18)))
    max_supply = int(_env("SCV_MAX_SUPPLY", "10000"))

    # 4. Metadata (web3:// placeholders pointing at the external renderer).
    renderer = _env("RENDERER_ADDRESS", ZERO_ADDRESS)
    suffix = _env("METADATA_SUFFIX", "")

    def base(path: str, var: str) -> str:
        return _env(var, f"web3://{renderer}:{chain_id}/{path}/")

    def contract_uri(path: str, var: str) -> str:
        return _env(var, f"web3://{renderer}:{chain_id}/{path}/contract")

    # 2. Deploy.
    planets = Planets.deploy(
        base("planets", "PLANETS_BASE_URI"), suffix, contract_uri("planets", "PLANETS_CONTRACT_URI")
    )
    scv = SCV.deploy(
        credits.address,
        treasury,
        burn_proceeds,
        price,
        max_supply,
        base("scv", "SCV_BASE_URI"),
        suffix,
        contract_uri("scv", "SCV_CONTRACT_URI"),
    )
    minerals = ResourceToken.deploy("Spacemine Minerals", "MNRL")
    gas = ResourceToken.deploy("Spacemine Gas", "GAS")
    mining = Mining.deploy(scv.address, planets.address, minerals.address, gas.address)
    spaceships = Spaceships.deploy(
        minerals.address,
        gas.address,
        treasury,
        base("ships", "SHIPS_BASE_URI"),
        suffix,
        contract_uri("ships", "SHIPS_CONTRACT_URI"),
    )

    # 3. Wire roles. `set_mining` is one-time on every contract. The resource
    # tokens revoked the deployer's minter role in their constructors.
    minerals.set_mining(mining.address)
    gas.set_mining(mining.address)
    scv.set_mining(mining.address)
    planets.set_mining(mining.address)

    royalty_bps = int(_env("ROYALTY_BPS", "500"))
    if royalty_bps:
        scv.set_default_royalty(treasury, royalty_bps)
        spaceships.set_default_royalty(treasury, royalty_bps)

    # 5. Demo seed (local networks by default; SEED_DEMO=1 forces it on live ones).
    if seed_demo is None:
        seed_demo = _env("SEED_DEMO", "1" if local else "0") == "1"
    if seed_demo:
        seed_demo_content(planets, mining, spaceships)

    deployment = Spacemine(credits, scv, planets, minerals, gas, mining, spaceships, treasury)
    if verbose:
        for field in ("credits", "scv", "planets", "minerals", "gas", "mining", "spaceships"):
            print(f"{field:>11}: {getattr(deployment, field).address}")
    return deployment


def _wei(tokens: str) -> int:
    """Whole-token decimal string (e.g. "0.5") to 18-decimal base units."""
    return int(Decimal(tokens) * E18)


def load_seed(path: Path | str | None = None) -> dict:
    return json.loads(Path(path or _env("SEED_FILE", str(DEMO_SEED))).read_text())


def seed_demo_content(
    planets: VyperContract, mining: VyperContract, spaceships: VyperContract, seed: dict | None = None
) -> None:
    """Create the planets, resource nodes, and ship types from the demo seed file."""
    seed = seed or load_seed()
    for world in seed["planets"]:
        planet_id = planets.create_planet(
            world["name"],
            BIOMES[world["biome"]],
            world["size"],
            world["coord_x"],
            world["coord_y"],
            world["mineral_richness_bps"],
            world["gas_richness_bps"],
        )
        for node in world["nodes"]:
            mining.create_node(planet_id, KINDS[node["kind"]], node["slots"], _wei(node["base_reserve"]), _wei(node["rate"]))

    for ship in seed["ships"]:
        spaceships.create_ship_type(
            ship["name"],
            SHIP_CLASSES[ship["class"]],
            _wei(ship["mineral_cost"]),
            _wei(ship["gas_cost"]),
            ship["max_supply"],
            ship["hull"],
            ship["shield"],
            ship["attack"],
            ship["speed"],
            ship["cargo"],
        )


def moccasin_main() -> Spacemine:
    return deploy(verbose=True)
