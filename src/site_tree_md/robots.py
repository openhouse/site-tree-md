from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from requests import Session


@dataclass(slots=True)
class RobotsCache:
    session: Session
    timeout: float
    user_agent: str
    parsers: dict[str, RobotFileParser] = field(default_factory=dict)

    def parser_for(self, url: str) -> RobotFileParser:
        split = urlsplit(url)
        origin = f"{split.scheme}://{split.netloc}"
        parser = self.parsers.get(origin)
        if parser is not None:
            return parser
        parser = RobotFileParser()
        try:
            response = self.session.get(urljoin(origin, "/robots.txt"), timeout=self.timeout)
            parser.parse(response.text.splitlines())
        except Exception:
            parser.parse([])
        self.parsers[origin] = parser
        return parser

    def can_fetch(self, url: str) -> bool:
        return self.parser_for(url).can_fetch(self.user_agent, url)
