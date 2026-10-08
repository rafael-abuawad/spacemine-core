# pragma version ~=0.4.3
"""
@title Mock ERC-721/ERC-1155 Receiver
@custom:contract-name MockReceiver
@license MIT
@notice Test-only token receiver. Depending on `mode`, the hooks
        accept (0), revert (1), attempt a re-entrant call with
        `reenter_data` into `reenter_target` (2), or return a
        wrong magic value (3). The outcome of the re-entrant call
        is recorded instead of bubbling up, so tests can observe it.
"""


from snekmate.tokens.interfaces import IERC721Receiver
implements: IERC721Receiver
from snekmate.tokens.interfaces import IERC1155Receiver
implements: IERC1155Receiver


MODE_ACCEPT: constant(uint8) = 0
MODE_REJECT: constant(uint8) = 1
MODE_REENTER: constant(uint8) = 2
MODE_WRONG_VALUE: constant(uint8) = 3


mode: public(uint8)
reenter_target: public(address)
reenter_data: public(Bytes[1_024])
reentry_attempts: public(uint256)
reentry_succeeded: public(bool)
received_count: public(uint256)


@external
def set_mode(mode_: uint8):
    self.mode = mode_


@external
def set_reentry(target: address, data: Bytes[1_024]):
    self.reenter_target = target
    self.reenter_data = data


@external
def execute(target: address, data: Bytes[2_048]) -> Bytes[1_024]:
    return raw_call(target, data, max_outsize=1_024)


@external
@view
def supportsInterface(interfaceId: bytes4) -> bool:
    return interfaceId in [0x01FFC9A7, 0x4E2312E0, 0x150B7A02]


@external
def onERC721Received(_operator: address, _from: address, _tokenId: uint256, _data: Bytes[1_024]) -> bytes4:
    self._hook()
    if self.mode == MODE_WRONG_VALUE:
        return 0x00000000
    return method_id("onERC721Received(address,address,uint256,bytes)", output_type=bytes4)


@external
def onERC1155Received(_operator: address, _from: address, _id: uint256, _value: uint256, _data: Bytes[1_024]) -> bytes4:
    self._hook()
    if self.mode == MODE_WRONG_VALUE:
        return 0x00000000
    return method_id("onERC1155Received(address,address,uint256,uint256,bytes)", output_type=bytes4)


@external
def onERC1155BatchReceived(
    _operator: address,
    _from: address,
    _ids: DynArray[uint256, 65_535],
    _values: DynArray[uint256, 65_535],
    _data: Bytes[1_024],
) -> bytes4:
    self._hook()
    if self.mode == MODE_WRONG_VALUE:
        return 0x00000000
    return method_id("onERC1155BatchReceived(address,address,uint256[],uint256[],bytes)", output_type=bytes4)


@internal
def _hook():
    self.received_count += 1
    if self.mode == MODE_REJECT:
        raise "receiver: rejected"
    if self.mode == MODE_REENTER:
        self.reentry_attempts += 1
        success: bool = raw_call(self.reenter_target, self.reenter_data, revert_on_failure=False)
        if success:
            self.reentry_succeeded = True
