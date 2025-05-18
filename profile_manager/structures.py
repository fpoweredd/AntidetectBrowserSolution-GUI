from dataclasses import dataclass, field
from typing import Union, List, Optional

from browserforge.fingerprints import Fingerprint


@dataclass
class Proxy:
    server: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None


@dataclass
class Profile:
    fingerprint: dict
    proxy: Optional[Proxy] = None
    page_urls: Optional[list[str]] = None


@dataclass
class ASocksSettings:
    api_key: str
    domain: str = "https://api.asocks.com"
