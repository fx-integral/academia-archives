from sqlalchemy.orm import (
    Session,
)
from subnet_validator.database.entities import (
    Category,
)


class CategoryService:
    """
    Service for adding or updating Category records in the database.
    """

    def __init__(
        self,
        db: Session,
    ):
        self.db = db

    def add_or_update_category(
        self,
        category_id: int,
        category_name: str,
    ) -> Category:
        """
        Add a new category or update an existing one by id.
        If the category exists, update its name. Otherwise, create a new category.
        Returns the Category instance.
        """
        category = (
            self.db.query(Category).filter(Category.id == category_id).first()
        )
        if category:
            category.name = category_name
        else:
            category = Category(
                id=category_id,
                name=category_name,
            )
            self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category
