"""Deliberately weakened variants of controls, one per control, switched on only by ``UNSAFE_*`` settings and only
under ``APP_ENV=test``. Tests run the same assertions with a weakness on and watch them fail, which proves each
control. Nothing in here is reachable in a normal run."""
