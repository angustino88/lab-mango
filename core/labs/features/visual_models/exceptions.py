class InvalidModel(ValueError):
    pass


class ModelConflict(Exception):
    """The stored version differs from the caller's precondition."""


class ModelNotFound(Exception):
    pass


class AssetInUse(Exception):
    def __init__(self, usage_count: int):
        super().__init__(f"The model is assigned to {usage_count} resource(s).")
        self.usage_count = usage_count
