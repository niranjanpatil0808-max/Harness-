from errors import InsufficientFunds, InvalidAmount


class Account:
    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = balance

    def deposit(self, amount):
        if amount <= 0:
            raise InvalidAmount(amount)
        self.balance += amount

    def withdraw(self, amount):
        if amount <= 0:
            raise InvalidAmount(amount)
        if amount > self.balance:
            raise InsufficientFunds(self.balance, amount)
        self.balance -= amount
