import unittest

from openaec_bim.tests import vereis_testsite


class TestTestsite(unittest.TestCase):
	def test_een_gewone_site_wordt_geweigerd(self):
		with self.assertRaisesRegex(RuntimeError, "klant0.cloud.open-aec.localhost"):
			vereis_testsite("klant0.cloud.open-aec.localhost")

	def test_een_naam_die_alleen_op_test_lijkt_wordt_geweigerd(self):
		with self.assertRaises(RuntimeError):
			vereis_testsite("testklant.cloud.open-aec.eu")

	def test_een_testsite_mag(self):
		vereis_testsite("test.localhost")

	def test_zonder_site_is_er_niets_te_wissen(self):
		vereis_testsite(None)
