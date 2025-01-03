from importlib.metadata import version

try:
    __version__ = version("cloudcoil")
except ImportError:
    __version__ = "0.0.0"
