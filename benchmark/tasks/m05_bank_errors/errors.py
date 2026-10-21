class BankError(Exception):
    """Base class for all banking errors."""


class InvalidAmount(BankError):
    pass


class InsufficientFunds(BankError):
    def __init__(self, balance, amount):
        super().__init__(f"balance {balance} is less than {amount}")
        self.balance = balance
        self.amount = amount
