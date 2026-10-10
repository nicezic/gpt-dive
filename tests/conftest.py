import pytest
from pydantic_ai import models


@pytest.fixture(autouse=True)
def block_real_model_requests():
    with models.override_allow_model_requests(False):
        yield
