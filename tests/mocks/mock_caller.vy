# pragma version ~=0.4.3
"""
@title Mock Caller (Non-Receiver Contract)
@custom:contract-name mock_caller
@license MIT
@notice Test-only contract that forwards arbitrary calls and
        implements no token receiver hooks.
"""


@external
def execute(target: address, data: Bytes[2_048]) -> Bytes[1_024]:
    return raw_call(target, data, max_outsize=1_024)
