from fiber.chain.models import Node as BaseNode
from pydantic import field_validator


class ExtendedNode(BaseNode):
    """Extension of fiber's Node with local-only fields.

    These fields are optional to remain backward compatible with any nodes file
    written by the library without our extensions.
    """

    version: str | None = None
    is_validator: bool = False

    def get_stake_weight(self) -> float:
        """Compute weight consistent with prior logic."""
        return self.alpha_stake + 0.18 * self.tao_stake

    def has_enough_weight(self, needed_weight: float) -> bool:
        return self.get_stake_weight() >= needed_weight

    @field_validator("ip", mode="before")
    @classmethod
    def normalize_ip(cls, v: str | int):
        try:
            n = int(v)
            import struct, socket

            return socket.inet_ntoa(struct.pack(">I", n))
        except Exception:
            return v
