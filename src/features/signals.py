"""Backward-compatible feature pipeline entry point."""

from .engine import calculate_features


def add_features(df):
    return calculate_features(df)
