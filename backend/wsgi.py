# PythonAnywhere / any WSGI host: point the WSGI file at `from wsgi import app`
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from app import app  # noqa
