"""Cicada's relay (G132 phase 3a): a store-and-forward mailbox for one person's devices that sees only ciphertext.

Standalone: it imports nothing from the backend, and nothing in the backend imports it. One container image is both
the hosted default and the self-host option (``relay/Dockerfile``; network.md, "The relay").
"""
__version__ = "0.1.0"
