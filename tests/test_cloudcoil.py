"""Tests for cloudcoil package."""

from cloudcoil import __version__


def test_version():
    """Test version is string."""
    assert isinstance(__version__, str)
