# pragma version ~=0.4.3
"""
@title Mock No-Return CREDITS
@custom:contract-name MockNoReturnCredits
@license MIT
@notice Test-only ERC-20 whose `transfer` and `transferFrom`
        return nothing (like legacy USDT).
"""


balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
totalSupply: public(uint256)


@external
def mint(owner: address, amount: uint256):
    self.balanceOf[owner] += amount
    self.totalSupply += amount


@external
def approve(spender: address, amount: uint256) -> bool:
    self.allowance[msg.sender][spender] = amount
    return True


@external
def transfer(to: address, amount: uint256):
    self.balanceOf[msg.sender] -= amount
    self.balanceOf[to] += amount


@external
def transferFrom(owner: address, to: address, amount: uint256):
    self.allowance[owner][msg.sender] -= amount
    self.balanceOf[owner] -= amount
    self.balanceOf[to] += amount
