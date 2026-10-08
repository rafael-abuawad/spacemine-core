"""Checks `interfaces/solidity/ISpacemine.sol` against the compiled Vyper ABIs.

For every function in each Solidity interface, the selector must exist in the matching
Vyper contract, with identical canonical input/output types and identical struct field
names. Every Solidity event must exist in the Vyper ABI with the same signature and
indexed flags. Requires `solc` on PATH (skipped otherwise).
"""

import json
import shutil
import subprocess

import pytest
from eth_utils import event_abi_to_log_topic, function_abi_to_4byte_selector

from helpers import ROOT

SOL_PATH = ROOT / "interfaces" / "solidity" / "ISpacemine.sol"
INTERFACE_TO_CONTRACT = {
    "ISCV": ["scv"],
    "IPlanets": ["planets"],
    "IMining": ["mining"],
    "ISpaceships": ["spaceships"],
    "ISpacemineContractMetadata": ["scv", "planets", "spaceships"],
}


def canonical(param: dict) -> str:
    kind = param["type"]
    if kind.startswith("tuple"):
        inner = ",".join(canonical(c) for c in param["components"])
        return f"({inner}){kind[len('tuple') :]}"
    return kind


def layout(params: list[dict]) -> list:
    """Types plus struct field names (top-level parameter names are ignored)."""

    def walk(param):
        if param["type"].startswith("tuple"):
            return [(c["name"], walk(c)) for c in param["components"]]
        return param["type"]

    return [walk(p) for p in params]


@pytest.fixture(scope="module")
def solidity_abis() -> dict[str, list[dict]]:
    solc = shutil.which("solc")
    if solc is None:
        pytest.skip("solc not installed")
    result = subprocess.run([solc, "--combined-json", "abi", str(SOL_PATH)], check=True, capture_output=True, text=True)
    contracts = json.loads(result.stdout)["contracts"]
    abis = {}
    for key, value in contracts.items():
        abi = value["abi"]
        abis[key.split(":")[-1]] = json.loads(abi) if isinstance(abi, str) else abi
    return abis


def test_all_interfaces_compiled(solidity_abis):
    assert set(INTERFACE_TO_CONTRACT) <= set(solidity_abis)


@pytest.mark.parametrize("interface", sorted(INTERFACE_TO_CONTRACT))
def test_functions_match_vyper(world, solidity_abis, interface):
    for contract_name in INTERFACE_TO_CONTRACT[interface]:
        vyper_abi = getattr(world, contract_name).abi
        vyper_fns = {function_abi_to_4byte_selector(f): f for f in vyper_abi if f["type"] == "function"}
        for fn in (f for f in solidity_abis[interface] if f["type"] == "function"):
            selector = function_abi_to_4byte_selector(fn)
            signature = f"{fn['name']}({','.join(canonical(i) for i in fn['inputs'])})"
            assert selector in vyper_fns, f"{interface}.{signature} missing from {contract_name}"
            vy = vyper_fns[selector]
            assert [canonical(o) for o in fn["outputs"]] == [canonical(o) for o in vy["outputs"]], signature
            assert layout(fn["outputs"]) == layout(vy["outputs"]), f"struct layout mismatch in {signature}"
            assert fn["stateMutability"] == vy["stateMutability"] == "view", signature


@pytest.mark.parametrize("interface", sorted(INTERFACE_TO_CONTRACT))
def test_events_match_vyper(world, solidity_abis, interface):
    for contract_name in INTERFACE_TO_CONTRACT[interface]:
        vyper_events = {event_abi_to_log_topic(e): e for e in getattr(world, contract_name).abi if e["type"] == "event"}
        for event in (e for e in solidity_abis[interface] if e["type"] == "event"):
            topic = event_abi_to_log_topic(event)
            assert topic in vyper_events, f"{interface}.{event['name']} missing from {contract_name}"
            assert [i["indexed"] for i in event["inputs"]] == [i["indexed"] for i in vyper_events[topic]["inputs"]]
