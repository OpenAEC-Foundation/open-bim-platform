"""Error type shared by all routes; serialised as {error_code, melding, remedie}."""


class KernError(Exception):
    def __init__(self, error_code: str, melding: str, remedie: str, status: int = 400) -> None:
        super().__init__(melding)
        self.error_code = error_code
        self.melding = melding
        self.remedie = remedie
        self.status = status

    def to_dict(self) -> dict[str, str]:
        return {"error_code": self.error_code, "melding": self.melding, "remedie": self.remedie}
