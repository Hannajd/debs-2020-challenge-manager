import unittest
import sys

sys.path.insert(0, '../')
from resources import Benchmark, BenchmarkSummary, BenchmarkResults

class BenchmarkTest(unittest.TestCase):
    #assertEquals(True, False)

    def test_upper(self):
        self.assertEqual('foo'.upper(), 'FOO')

    # def test_nothing(self):
    #     self.fail("shouldn't happen")

    def test_date_comparison(self):
        time_diff = Benchmark.compute_score([10, 12, u'2018-11-29 18:10:35.624916', u'2018-11-29 18:10:36.810949'])
        self.assertEqual(time_diff, 1)

# def suite():
#     suite = TestSuite()
#     suite.addTest(makeSuite(MeasurementsTest))
#     return suite
#
# runner = TextTestRunner(verbosity=3)
# result = runner.run(suite())

if __name__ == '__main__':
    unittest.main()
