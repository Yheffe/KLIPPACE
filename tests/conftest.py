"""Shared pytest fixtures for the KLIPPACE test suite."""

from __future__ import annotations

import pytest


@pytest.fixture
def ace_instance_cls():
    """The AceInstance class, exposing the authoritative material table."""
    from extras.ace.instance import AceInstance

    return AceInstance
