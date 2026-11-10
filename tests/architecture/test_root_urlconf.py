"""Regression coverage for project URL configuration importability."""

from importlib import import_module


def test_root_urlconf_imports():
    urlconf = import_module("config.urls")

    assert urlconf.urlpatterns
