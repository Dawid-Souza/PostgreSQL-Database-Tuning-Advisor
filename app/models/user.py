from dataclasses import dataclass


@dataclass
class User:
    username: str
    is_authenticated: bool = False

