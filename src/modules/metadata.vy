# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Shared `web3://` Metadata Storage
@custom:contract-name metadata
@license MIT
@notice Storage and helpers shared by the Spacemine NFT collections
        (SCV, Planets, Spaceships) for:
        - a mutable token-URI scheme `metadata_base || id || metadata_suffix`
          (snekmate's ERC-721/ERC-1155 base URIs are `immutable` and capped
          at 80 characters, so they are not used),
        - ERC-7572 contract-level metadata via `contractURI`:
          https://eips.ethereum.org/EIPS/eip-7572.
        All strings are treated as opaque. The intended values are
        ERC-4804 `web3://` URIs that resolve to an external renderer,
        but this module neither hard-codes nor parses any format.
        The module has no access control. The importing contract
        must guard the setters (e.g. with `ownable._check_owner`)
        and emit the token-standard-specific refresh events
        (ERC-4906 `BatchMetadataUpdate` or ERC-1155 `URI`).
"""


# @dev The maximum length of the token-URI prefix.
MAX_BASE_LENGTH: constant(uint256) = 160


# @dev The maximum length of the token-URI suffix.
MAX_SUFFIX_LENGTH: constant(uint256) = 32


# @dev The maximum length of `contractURI`.
MAX_CONTRACT_URI_LENGTH: constant(uint256) = 256


# @dev Returns the token-URI prefix, e.g.
# `web3://0x<renderer>:<chainId>/scv/`.
# @notice If you declare a variable as `public`,
# Vyper automatically generates an `external`
# getter function for the variable.
metadata_base: public(String[MAX_BASE_LENGTH])


# @dev Returns the token-URI suffix, e.g. `""` or `.json`.
metadata_suffix: public(String[MAX_SUFFIX_LENGTH])


# @dev Returns the ERC-7572 contract-level metadata URI.
contractURI: public(String[MAX_CONTRACT_URI_LENGTH])


# @dev Emitted when `contractURI` changes (ERC-7572).
event ContractURIUpdated:
    pass


# @dev Emitted when the token-URI prefix or suffix changes.
event MetadataURIUpdated:
    base: String[MAX_BASE_LENGTH]
    suffix: String[MAX_SUFFIX_LENGTH]


@deploy
@payable
def __init__(
    base_: String[MAX_BASE_LENGTH], suffix_: String[MAX_SUFFIX_LENGTH], contract_uri_: String[MAX_CONTRACT_URI_LENGTH]
):
    """
    @dev To omit the opcodes for checking the `msg.value`
         in the creation-time EVM bytecode, the constructor
         is declared as `payable`.
    @notice `ContractURIUpdated` is only emitted if a non-empty
            `contract_uri_` is set at construction time.
    @param base_ The maximum 160-character token-URI prefix.
    @param suffix_ The maximum 32-character token-URI suffix.
    @param contract_uri_ The maximum 256-character contract URI.
    """
    self.metadata_base = base_
    self.metadata_suffix = suffix_
    if len(contract_uri_) != empty(uint256):
        self._set_contract_uri(contract_uri_)


@internal
@view
def _token_uri(token_id: uint256) -> String[270]:
    """
    @dev Returns `metadata_base || uint2str(token_id) || metadata_suffix`.
    @notice The literal ID is concatenated (no `{id}` placeholder)
            because `web3://` renderers need the concrete ID.
            The maximum length is 160 + 78 + 32 = 270 characters.
    @param token_id The 32-byte identifier of the token.
    @return String The concatenated token URI.
    """
    return concat(self.metadata_base, uint2str(token_id), self.metadata_suffix)


@internal
def _set_metadata_uri(base_: String[MAX_BASE_LENGTH], suffix_: String[MAX_SUFFIX_LENGTH]):
    """
    @dev Sets the token-URI prefix and suffix.
    @notice This is an `internal` function without access restriction.
    @param base_ The maximum 160-character token-URI prefix.
    @param suffix_ The maximum 32-character token-URI suffix.
    """
    self.metadata_base = base_
    self.metadata_suffix = suffix_
    log MetadataURIUpdated(base=base_, suffix=suffix_)


@internal
def _set_contract_uri(contract_uri_: String[MAX_CONTRACT_URI_LENGTH]):
    """
    @dev Sets the ERC-7572 contract URI and emits `ContractURIUpdated`.
    @notice This is an `internal` function without access restriction.
    @param contract_uri_ The maximum 256-character contract URI.
    """
    self.contractURI = contract_uri_
    log ContractURIUpdated()
