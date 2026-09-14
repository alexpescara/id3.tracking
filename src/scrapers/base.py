from abc import ABC, abstractmethod
from typing import Any


class BaseScraper(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def search(self, search_url: str) -> list[dict[str, Any]]:
        raise NotImplementedError
