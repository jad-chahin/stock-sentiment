import sys
import time

class ProgressBar:
    def __init__(self, total: int, prefix: str = "", width: int = 30):
        self.total = max(1, int(total))
        self.prefix = prefix
        self.width = max(5, int(width))
        self.start = time.time()
        self.last_draw = 0.0
        self._use_rich = False
        self._stopped = False

        try:
            from rich.console import Console
            from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

            self._console = Console()
            self._progress = Progress(
                SpinnerColumn(spinner_name="line"),
                TextColumn("{task.description}"),
                BarColumn(bar_width=self.width),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=self._console,
                transient=True,
            )
            self._task_id = self._progress.add_task(self.prefix, total=self.total)
            self._progress.start()
            self._use_rich = True
        except Exception:
            self._use_rich = False

    def _stop_rich(self) -> None:
        if self._use_rich and not self._stopped:
            self._progress.stop()
            self._stopped = True

    def update(self, current: int) -> None:
        now = time.time()

        if now - self.last_draw < 0.1 and current < self.total:
            return
        self.last_draw = now

        cur = max(0, min(int(current), self.total))
        frac = cur / self.total

        if self._use_rich:
            self._progress.update(self._task_id, completed=cur)
            if cur >= self.total:
                self._stop_rich()
            return

        filled = int(self.width * frac)
        bar = "=" * filled + "." * (self.width - filled)
        elapsed = int(now - self.start)

        msg = f"\r{self.prefix} [{bar}] {cur}/{self.total} ({frac * 100:5.1f}%)  {elapsed}s"
        sys.stdout.write(msg)
        sys.stdout.flush()

        if cur >= self.total:
            sys.stdout.write("\n")
            sys.stdout.flush()

    def close(self) -> None:
        self._stop_rich()
