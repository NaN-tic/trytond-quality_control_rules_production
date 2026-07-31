from . import production

__all__ = ['register']


def register():
    production.register()
