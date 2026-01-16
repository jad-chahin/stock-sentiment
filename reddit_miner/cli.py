import os
import time
import datetime
import argparse
import sys

import prawcore
import openai

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from .config import RunConfig
from . import db as dbmod
from .pipeline import scrape, analyze
from .db import fetch_ticker_summary
from .report import print_report_rich
from . import ticker as tickermod
from .credentials import (
    ensure_credentials,
    load_into_env_if_missing,
    set_openai_key_interactive,
    set_reddit_credentials_interactive,
    reset_all,
)

console = Console()
_INTRO_SHOWN = False
_ALT_SCREEN_ON = False

def clear_screen() -> None:
    try:
        console.clear()
    except Exception:
        os.system("cls" if os.name == "nt" else "clear")

def _enter_alt_screen() -> None:
    global _ALT_SCREEN_ON
    if _ALT_SCREEN_ON:
        return
    _ALT_SCREEN_ON = True
    try:
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
        sys.stdout.flush()
    except Exception:
        _ALT_SCREEN_ON = False

def _exit_alt_screen() -> None:
    global _ALT_SCREEN_ON
    if not _ALT_SCREEN_ON:
        return
    _ALT_SCREEN_ON = False
    try:
        sys.stdout.write("\x1b[?1049l\x1b[?25h")
        sys.stdout.flush()
    except Exception:
        return

def _read_key() -> str:
    if os.name == "nt":
        try:
            import msvcrt
        except Exception:
            return input().strip().lower()
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            if ch2 == b"H":
                return "up"
            if ch2 == b"P":
                return "down"
            return ""
        if ch == b"\r":
            return "enter"
        try:
            return ch.decode(errors="ignore").lower()
        except Exception:
            return ""

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "up"
            if seq == "[B":
                return "down"
            return ""
        if ch in ("\r", "\n"):
            return "enter"
        return ch.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

def _print_info(msg: str) -> None:
    console.print(msg)

def _print_warn(msg: str) -> None:
    console.print(f"[yellow]WARN:[/yellow] {msg}")

def _print_error(msg: str) -> None:
    console.print(f"[bold red]ERROR:[/bold red] {msg}")

def _menu(title: str, options: list[tuple[str, str]]) -> str:
    clear_screen()
    valid = [k.lower() for k, _ in options]
    idx = 0
    while True:
        lines = []
        for i, (key, label) in enumerate(options):
            marker = ">" if i == idx else " "
            lines.append(f"{marker} [{key}] {label}")
        lines.append("")
        lines.append("Use Up/Down and Enter, or type a choice key.")
        console.print(
            Panel(
                "\n".join(lines),
                title=Text(title, style="bold cyan"),
                box=box.ASCII,
                expand=False,
            )
        )

        key = _read_key()
        if key == "up":
            idx = (idx - 1) % len(options)
            clear_screen()
            continue
        if key == "down":
            idx = (idx + 1) % len(options)
            clear_screen()
            continue
        if key == "enter":
            return options[idx][0].lower()
        if key and key in valid:
            return key
        clear_screen()

def _ask_yes_no(prompt: str) -> bool:
    try:
        return bool(Confirm.ask(prompt, default=False))
    except Exception:
        while True:
            ans = input(f"{prompt} (y/n): ").strip().lower()
            if ans in {"y", "yes"}:
                return True
            if ans in {"n", "no"}:
                return False
            _print_warn("Please enter y or n.")

def _pause(msg: str = "Press Enter to continue...") -> None:
    console.print(f"\n{msg}")
    input()

def _intro() -> None:
    global _INTRO_SHOWN
    if _INTRO_SHOWN:
        return
    _INTRO_SHOWN = True

    logo_lines = [
        " ____  _____ _   _ _____ ___ __  __ _____ _   _ _____ ",
        "/ ___|| ____| \\ | |_   _|_ _|  \\/  | ____| \\ | |_   _|",
        "\\___ \\|  _| |  \\| | | |  | || |\\/| |  _| |  \\| | | |  ",
        " ___) | |___| |\\  | | |  | || |  | | |___| |\\  | | |  ",
        "|____/|_____|_| \\_| |_| |___|_|  |_|_____|_| \\_| |_|  ",
        "                     v1.0",
    ]

    clear_screen()
    console.print(Panel("\n".join(logo_lines), title="Sentiment Alpha", style="cyan", box=box.ASCII, expand=False))
    console.print("[bold]Preparing menu[/bold]")
    _pause("Press Enter to continue...")
    clear_screen()

def _clear_credential_env() -> None:
    for k in ["OPENAI_API_KEY", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT"]:
        os.environ.pop(k, None)

def _setup_menu() -> None:
    while True:
        choice = _menu(
            "Setup:",
            [
                ("1", "Set / change OpenAI API key"),
                ("2", "Set / change Reddit credentials"),
                ("3", "Reset / remove saved credentials"),
                ("b", "Back"),
            ],
        )

        if choice == "1":
            set_openai_key_interactive()
            os.environ.pop("OPENAI_API_KEY", None)
            load_into_env_if_missing()
            _pause()

        elif choice == "2":
            set_reddit_credentials_interactive()
            os.environ.pop("REDDIT_CLIENT_ID", None)
            os.environ.pop("REDDIT_CLIENT_SECRET", None)
            os.environ.pop("REDDIT_USER_AGENT", None)
            load_into_env_if_missing()
            _pause()

        elif choice == "3":
            confirm = Prompt.ask("Type 'reset' to confirm").strip().lower()
            if confirm == "reset":
                reset_all()
                _clear_credential_env()
                _print_info("Credentials removed.")
            else:
                _print_warn("Cancelled.")
            _pause()

        elif choice == "b":
            return

def _choose_config_for_run(*, do_scrape: bool, do_analyze: bool) -> RunConfig | None:
    choice = _menu("Run settings:", [("1", "Default"), ("2", "Choose settings"), ("b", "Back")])
    if choice == "b":
        return None
    if choice == "1":
        return RunConfig.defaults()
    return RunConfig.from_user_input(do_scrape=do_scrape, do_analyze=do_analyze)

def _report_flow() -> None:
    cfg = RunConfig.defaults()
    if not os.path.exists(cfg.db_path):
        _print_warn(f"No database found at: {cfg.db_path}")
        _pause()
        return

    conn = dbmod.connect(cfg.db_path)
    dbmod.init_db(conn)

    tag = dbmod.get_latest_analysis_tag(conn)
    if not tag:
        _print_warn("No analysis found yet in this database.")
        _pause()
        return

    rows = fetch_ticker_summary(conn, analysis_tag=tag, subreddits=None, limit=500)

    summary = {
        "db_path": cfg.db_path,
        "subreddits": cfg.subreddits,
        "listing": cfg.listing,
        "post_limit": cfg.post_limit,
        "max_comments_per_post": cfg.max_comments_per_post,
        "analysis_tag": tag,
        "model": "-",
        "saved": "-",
        "analyzed_model_calls": "-",
    }
    print_report_rich(summary=summary, rows=rows, top_n=cfg.top_n)

    return

def _pick_tag_for_clear(conn) -> str | None:
    tags = dbmod.list_analysis_tags(conn)
    if not tags:
        _print_warn("No analysis tags found in this database.")
        _pause()
        return None

    options = [(str(i + 1), tags[i]) for i in range(len(tags))]
    options.append(("b", "Back"))
    choice = _menu("Select analysis tag:", options)
    if choice == "b":
        return None
    idx = int(choice) - 1
    if 0 <= idx < len(tags):
        return tags[idx]
    return None

def _clear_analysis(conn, *, analysis_tag: str) -> tuple[int, int]:
    cur1 = conn.execute("DELETE FROM mentions WHERE analysis_tag = ?", (analysis_tag,))
    cur2 = conn.execute("DELETE FROM comment_analysis WHERE analysis_tag = ?", (analysis_tag,))
    conn.commit()
    return cur1.rowcount or 0, cur2.rowcount or 0

def _clear_dataset(conn) -> tuple[int, int, int]:
    cur1 = conn.execute("DELETE FROM mentions")
    cur2 = conn.execute("DELETE FROM comment_analysis")
    cur3 = conn.execute("DELETE FROM comments")
    conn.commit()
    return cur1.rowcount or 0, cur2.rowcount or 0, cur3.rowcount or 0

def _clear_flow() -> None:
    cfg = RunConfig.defaults()
    if not os.path.exists(cfg.db_path):
        _print_warn(f"No database found at: {cfg.db_path}")
        _pause()
        return

    conn = dbmod.connect(cfg.db_path)
    dbmod.init_db(conn)

    while True:
        choice = _menu(
            "Clear:",
            [
                ("1", "Clear analysis (pick a tag)"),
                ("2", "Clear dataset (comments + ALL analysis)"),
                ("b", "Back"),
            ],
        )

        if choice == "b":
            return

        if choice == "1":
            tag = _pick_tag_for_clear(conn)
            if not tag:
                continue
            _print_warn(f"This will delete mentions + analysis for tag: {tag}")
            if not _ask_yes_no("Continue?"):
                continue
            dm, da = _clear_analysis(conn, analysis_tag=tag)
            _print_info(f"Cleared: {dm} mentions, {da} analysis rows.")
            _pause()
            continue

        if choice == "2":
            _print_warn("This will delete ALL comments and ALL analysis from this database.")
            if not _ask_yes_no("Continue?"):
                continue
            dm, da, dc = _clear_dataset(conn)
            _print_info(f"Cleared: {dm} mentions, {da} analysis rows, {dc} comments.")
            _pause()
            continue

def _run_flow() -> None:
    action = _menu(
        "What do you want to do?",
        [
            ("1", "Scrape data"),
            ("2", "Analyze scraped data"),
            ("3", "Scrape then analyze"),
            ("b", "Back"),
        ],
    )
    if action == "b":
        return

    do_scrape = action in {"1", "3"}
    do_analyze = action in {"2", "3"}

    cfg = _choose_config_for_run(do_scrape=do_scrape, do_analyze=do_analyze)
    if cfg is None:
        return

    need_reddit = do_scrape
    need_openai = do_analyze

    try:
        ensure_credentials(need_openai=need_openai, need_reddit=need_reddit)
        load_into_env_if_missing()
    except KeyboardInterrupt:
        _print_info("Back.")
        return

    conn = dbmod.connect(cfg.db_path)
    dbmod.init_db(conn)

    start = time.time()
    saved = 0
    outcome = None

    if do_scrape:
        _print_info("Scraping started. Press Q to stop and save what's been collected so far.")
        try:
            saved = scrape(
                conn,
                subreddits=cfg.subreddits,
                listing=cfg.listing,
                post_limit=cfg.post_limit,
                more_limit=cfg.more_limit,
                max_comments_per_post=cfg.max_comments_per_post,
                bot_usernames=cfg.bot_usernames,
            )
            conn.commit()
        except KeyboardInterrupt:
            conn.commit()
            _print_warn("Scrape stopped. Data collected so far has been saved.")
            if action == "3":
                next_choice = _menu(
                    "Scrape interrupted:",
                    [("1", "Skip remaining scraping and start analysis now"), ("2", "Stop (back to main menu)")],
                )
                if next_choice == "2":
                    elapsed = datetime.timedelta(seconds=int(time.time() - start))
                    _print_info(f"Time elapsed: {elapsed}")
                    _pause()
                    return
        except (prawcore.exceptions.OAuthException, prawcore.exceptions.ResponseException, prawcore.exceptions.Forbidden) as e:
            _print_error("Reddit credentials appear invalid or unauthorized.")
            _print_info(f"Details: {e}")
            if _ask_yes_no("Open Setup to update them now?"):
                _setup_menu()
            return
        except Exception as e:
            conn.commit()
            _print_error("Scrape failed.")
            _print_info(str(e))
            _pause()
            return

    if do_analyze:
        _print_info("Analysis started. Press Q to stop and save what's been analyzed so far.")
        try:
            outcome = analyze(
                conn,
                analysis_tag=cfg.analysis_tag,
                model=cfg.model,
                limit=cfg.analysis_limit,
                retry_errors=False,
                max_requests_per_minute=cfg.max_requests_per_minute,
                subreddits=cfg.subreddits,
            )
            conn.commit()
        except KeyboardInterrupt:
            conn.commit()
            _print_warn("Analysis stopped. Results analyzed so far have been saved.")

        except openai.AuthenticationError as e:
            _print_error("OpenAI API key appears invalid.")
            _print_info(f"Details: {e}")
            if _ask_yes_no("Open Setup to update it now?"):
                _setup_menu()
            return

        except openai.PermissionDeniedError as e:
            _print_error("OpenAI request was denied (403). Retrying a few times...")
            _print_info(f"Details: {e}")

            for attempt in range(3):
                try:
                    time.sleep(2 ** attempt)
                    outcome = analyze(
                        conn,
                        analysis_tag=cfg.analysis_tag,
                        model=cfg.model,
                        limit=cfg.analysis_limit,
                        retry_errors=False,
                        max_requests_per_minute=cfg.max_requests_per_minute,
                        subreddits=cfg.subreddits,
                    )
                    conn.commit()
                    break
                except openai.PermissionDeniedError as e2:
                    _print_warn(f"Still denied (attempt {attempt+1}/3). Details: {e2}")
            else:
                _print_error("Still denied after retries. Stopping.")
                if _ask_yes_no("Open Setup to update it now?"):
                    _setup_menu()
                return

        except Exception as e:
            conn.commit()
            _print_error("Analysis failed.")
            _print_info(str(e))
            _pause()
            return

        summary_rows = fetch_ticker_summary(conn, analysis_tag=cfg.analysis_tag, subreddits=cfg.subreddits, limit=500)

        analyzed_calls = getattr(outcome, "analyzed_model_calls", "-") if outcome is not None else "-"
        summary = {
            "db_path": cfg.db_path,
            "subreddits": cfg.subreddits,
            "listing": cfg.listing,
            "post_limit": cfg.post_limit,
            "max_comments_per_post": cfg.max_comments_per_post,
            "analysis_tag": cfg.analysis_tag,
            "model": cfg.model,
            "saved": saved,
            "analyzed_model_calls": analyzed_calls,
        }
        print_report_rich(summary=summary, rows=summary_rows, top_n=cfg.top_n)

    elapsed = datetime.timedelta(seconds=int(time.time() - start))
    _print_info(f"Time elapsed: {elapsed}")
    _pause()

def run() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Enable yfinance validation: after analysis, delete mentions for tickers that yfinance says are invalid.",
    )
    parser.add_argument(
        "--shortcut",
        action="store_true",
        help="Enable keyword shortcut: skip OpenAI analysis for comments unlikely to contain tickers/finance context.",
    )
    args, _unknown = parser.parse_known_args()

    tickermod.ENABLE_YFINANCE_VALIDATION = bool(args.validate)
    tickermod.ENABLE_KEYWORD_SHORTCUT = bool(args.shortcut)

    load_into_env_if_missing()

    _enter_alt_screen()
    try:
        _intro()
        while True:
            choice = _menu(
                "Main menu:",
                [("1", "Run"), ("2", "Report"), ("3", "Clear"), ("4", "Setup"), ("q", "Quit")],
            )

            if choice == "q":
                return
            if choice == "1":
                _run_flow()
            elif choice == "2":
                _report_flow()
            elif choice == "3":
                _clear_flow()
            elif choice == "4":
                _setup_menu()
    finally:
        _exit_alt_screen()
