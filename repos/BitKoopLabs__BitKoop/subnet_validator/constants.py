import enum
from fiber import (
    constants,
)


class CouponStatus(enum.IntEnum):
    INVALID = 0
    VALID = 1
    PENDING = 2
    EXPIRED = 3
    USED = 4
    DELETED = 5
    DUPLICATE = 6


class CouponAction(enum.IntEnum):
    CREATE = 0
    RECHECK = 1
    DELETE = 2


class SiteStatus(enum.IntEnum):
    INACTIVE = 0
    ACTIVE = 1
    PENDING = 2


NETWORK_TO_NETUID = {
    constants.FINNEY_NETWORK: 16,
    constants.FINNEY_TEST_NETWORK: 368,
}

SUPERVISOR_API_URL = {
    constants.FINNEY_NETWORK: "http://49.13.237.126/api",
    constants.FINNEY_TEST_NETWORK: "http://91.99.203.36/api",
}
