"""Include the original database checks in unittest discovery."""

import unittest

from tests import check_database


class DatabaseTests(unittest.TestCase):
    def test_construction(self):
        check_database.test_db_construction()

    def test_insert_and_read(self):
        check_database.test_db_add_read()

    def test_duplicate_email(self):
        check_database.test_duplicate_email()


if __name__ == "__main__":
    unittest.main()
