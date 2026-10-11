import boa
import pytest

from helpers import RENDERER, TERRAN
from script.deploy import deploy

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


@pytest.fixture
def deployer():
    return boa.env.eoa


@pytest.fixture
def alice():
    return boa.env.generate_address("alice")


@pytest.fixture
def bob():
    return boa.env.generate_address("bob")


@pytest.fixture
def carol():
    return boa.env.generate_address("carol")


# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------


@pytest.fixture
def world(monkeypatch):
    for var in ("SCV_BASE_URI", "PLANETS_BASE_URI", "SHIPS_BASE_URI"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("RENDERER_ADDRESS", RENDERER)
    monkeypatch.setenv("METADATA_SUFFIX", "")
    d = deploy(seed_demo=False)
    d.scv.set_sale_active(True)
    return d


@pytest.fixture
def credits(world):
    return world.credits


@pytest.fixture
def scv(world):
    return world.scv


@pytest.fixture
def planets(world):
    return world.planets


@pytest.fixture
def mining(world):
    return world.mining


@pytest.fixture
def minerals(world):
    return world.minerals


@pytest.fixture
def gas(world):
    return world.gas


@pytest.fixture
def spaceships(world):
    return world.spaceships


@pytest.fixture
def planet_id(planets):
    # Neutral richness so `reserve == base_reserve` for both kinds.
    return planets.create_planet("Testworld", TERRAN, 5, 0, 0, 10_000, 10_000)
