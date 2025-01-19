import pydantic


class BaseModel(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        populate_by_name=True,
        validate_default=True,
        validate_assignment=True,
    )
