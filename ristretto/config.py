"""
.. module:: Ristretto config
   :platform: Linux
   :synopsis: configurarion of the framework
   :copyright: (c) 2013 by Ernesto Bossi.
   :license: GPL v3.

.. moduleauthor:: Ernesto Bossi <bossi.ernestog@gmail.com>

"""

import types
import os
from .utils.util import wrap_exception, check_for_file


class ConfigProxy(object):
    """Makes an attribute forward to the config"""

    def __init__(self, name, get_converter=None):
        self.__name__ = name
        self.get_converter = get_converter

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        rv = obj.config[self.__name__]
        if self.get_converter is not None:
            rv = self.get_converter(rv)
        return rv

    def __set__(self, obj, value):
        obj.config[self.__name__] = value


class Configuration(dict):
    def __init__(self, root_path, default_dict=None):
        self.root_path = root_path
        dict.__init__(self, default_dict or {})

    def import_from_py(self, py_file):
        if not check_for_file(self.root_path, py_file):
            raise EnvironmentError('file {0} does not exists or wrong path'.format(py_file))
        filename = os.path.join(self.root_path, py_file)
        mod = types.ModuleType('config')
        mod.filename = py_file
        try:
            with open(filename, 'rb') as config_file:
                config_compiled = compile(config_file.read(), filename, 'exec')
                exec(config_compiled, mod.__dict__)
            self.clean_builtins(mod.__dict__)

            self.update(mod.__dict__)
        except IOError:
            wrap_exception(EnvironmentError, 'error processing file config {0}'.format(py_file))

    def clean_builtins(self, dictionary):
        del dictionary['__builtins__']

    def import_from_environ(self, environ_var):
        evar = os.environ.get(environ_var)
        if not evar:
            raise EnvironmentError('Enviroment variable {0} is not a valid one'.format(environ_var))
        if os.path.isfile(evar):
            self.import_from_py(evar)
        else:
            self[environ_var] = evar

    def import_from_object(self, object_instance):
        for key in dir(object_instance):
            if key.isupper():
                self[key] = getattr(object_instance, key)

    def __repr__(self):
        return '<{0} {1}>'.format(self.__class__.__name__, dict.__repr__(self))