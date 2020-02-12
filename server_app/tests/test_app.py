import unittest
import json
import sys
sys.path.insert(0, './')
from app import app


class TestHome():
    def test_home(self):
        with app.test_client() as c:
            resp = c.get('/')

            self.assertEqual(resp.status_code, (200 | 201))
            # self.assertEqual(json.loads(resp.get_data()), { 'message': ''})


if __name__ == '__main__':
    unittest.main()
