class GrabBlocked(Exception):
    """Raised when grabbing must not proceed right now (VPN down, disk full, ...)."""


class LowDiskSpace(GrabBlocked):
    pass
