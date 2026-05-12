from sqlalchemy.orm import Session
from subnet_validator.database.entities import MetagraphNode
from fiber.chain.models import Node
from typing import Optional
from subnet_validator import __version__ as version


class MetagraphService:
    """
    Service for managing MetagraphNode records.
    """

    def __init__(self, db: Session):
        self.db = db

    def create_or_update_node(
        self,
        node: Node,
        validator_version: str | None = None,
        is_enough_weight: bool | None = None,
    ) -> bool:
        """
        Creates or updates a MetagraphNode record from a fiber Node.

        Args:
            node: Node from fiber.chain.models

        Returns:
            bool: True if a new node was created, False if an existing node was updated
        """
        # Check if node already exists by hotkey
        existing_node = self.db.get(MetagraphNode, node.node_id)

        if existing_node:
            # Update existing node
            existing_node.hotkey = node.hotkey
            existing_node.coldkey = node.coldkey
            existing_node.netuid = node.netuid
            existing_node.alpha_stake = node.alpha_stake
            existing_node.tao_stake = node.tao_stake
            existing_node.stake = node.stake
            existing_node.ip = node.ip
            existing_node.ip_type = node.ip_type
            existing_node.protocol = node.protocol
            existing_node.port = node.port
            existing_node.validator_version = validator_version
            existing_node.is_enough_weight = is_enough_weight

            self.db.commit()
            return False  # Updated existing node
        else:
            # Create new node
            new_node = MetagraphNode(
                id=node.node_id,
                hotkey=node.hotkey,
                coldkey=node.coldkey,
                netuid=node.netuid,
                alpha_stake=node.alpha_stake,
                tao_stake=node.tao_stake,
                stake=node.stake,
                ip=node.ip,
                ip_type=node.ip_type,
                protocol=node.protocol,
                port=node.port,
                validator_version=validator_version,
                is_enough_weight=is_enough_weight,
            )

            self.db.add(new_node)
            self.db.commit()
            return True  # Created new node

    def get_validator_nodes(self) -> list[Node]:
        nodes = (
            self.db.query(MetagraphNode)
            .filter(MetagraphNode.validator_version == version)
            .filter(MetagraphNode.is_enough_weight == True)
            .all()
        )
        return [self.to_node(node) for node in nodes]

    def is_miner_hotkey_exists(self, hotkey: str, coldkey: str = None) -> bool:
        query = (
            self.db.query(MetagraphNode)
            .filter(MetagraphNode.hotkey == hotkey)
            .filter(MetagraphNode.validator_version == None)
        )

        if coldkey is not None:
            query = query.filter(MetagraphNode.coldkey == coldkey)

        return query.first() is not None

    def get_node_by_hotkey(self, hotkey: str) -> Optional[Node]:
        node = (
            self.db.query(MetagraphNode)
            .filter(MetagraphNode.hotkey == hotkey)
            .first()
        )
        return self.to_node(node) if node else None

    def get_miner_nodes(self) -> list[Node]:
        nodes = (
            self.db.query(MetagraphNode)
            .filter(MetagraphNode.validator_version == None)
            .all()
        )
        return [self.to_node(node) for node in nodes]

    @classmethod
    def to_node(cls, node: MetagraphNode) -> Node:
        return Node(
            node_id=node.id,
            hotkey=node.hotkey,
            coldkey=node.coldkey,
            netuid=node.netuid,
            alpha_stake=node.alpha_stake,
            tao_stake=node.tao_stake,
            stake=node.stake,
            ip=node.ip,
            ip_type=node.ip_type,
            protocol=node.protocol,
            port=node.port,
            incentive=0.0,
            trust=0.0,
            vtrust=0.0,
            last_updated=0.0,
        )
