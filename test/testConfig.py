from unittest import TestCase
from test.resource.configResource import ObjectTest
from ristretto.config import Configuration
import os

TESTING_FILEPATH = './resource/configFileTest.py'


class TestConfiguration(TestCase):

    def setUp(self):
        self.obj = ObjectTest()
        self.file = TESTING_FILEPATH
        self.config = Configuration(os.getcwd())

    def test_import_from_file(self):
        self.config.import_from_py(TESTING_FILEPATH)
        print(self.config)
        self.assertIn('Avariable',self.config)

    def test_import_from_object(self):
        self.config.import_from_object(self.obj)
        self.assertIn('ACONSTANT', self.config)
        self.assertNotIn('a_variable', self.config)

    def test_import_from_environ(self):
        env = os.environ
        try:
            os.environ = {'CONSTANT': 1}
            self.config.import_from_environ('CONSTANT')
            self.assertIn('CONSTANT', self.config)
        finally:
            os.environ = env