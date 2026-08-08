from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List
class Sandbox(ABC):
    @property
    @abstractmethod
    def id(self) -> str:
        ...
    @abstractmethod
    def execute_command(self, command: str) -> str:
        ...
    @abstractmethod
    def read_file(self, path: str) -> str:
        ...
    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        ...
    @abstractmethod
    def list_dir(self, path: str, max_depth: int = 2) -> List[str]:
        ...
    @abstractmethod
    def update_file(self, path: str, content: bytes) -> None:
        ...