import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

Email = Annotated[EmailStr, AfterValidator(str.lower)]

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class RegisterRequest(BaseModel):
    email: Email
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH, repr=False
    )


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime
