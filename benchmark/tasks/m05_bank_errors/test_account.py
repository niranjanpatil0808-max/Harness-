import unittest

from account import Account
from errors import InsufficientFunds


class TestWithdraw(unittest.TestCase):
    def test_ok(self):
        acct = Account("ravi", 100)
        acct.withdraw(30)
        self.assertEqual(acct.balance, 70)

    def test_overdraw(self):
        acct = Account("ravi", 50)
        with self.assertRaises(InsufficientFunds):
            acct.withdraw(80)
        self.assertEqual(acct.balance, 50)
