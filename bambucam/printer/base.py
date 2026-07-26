from __future__ import annotations

from abc import ABC, abstractmethod

from bambucam.models import PrintJob


class PrinterProvider(ABC):
    @abstractmethod
    def get_current_job(self) -> PrintJob | None:
        """Return the currently active print job, or None if idle."""
        ...

    @abstractmethod
    def get_status(self) -> str:
        """Return current printer status string."""
        ...

    @abstractmethod
    def is_printing(self) -> bool:
        """Check if a print is currently in progress."""
        ...
