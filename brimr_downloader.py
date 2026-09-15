#!/usr/bin/env python3
"""
BRIMR NIH Funding Data Downloader

Downloads Excel files from BRIMR over HTTPS, no browser required.
Automatically detects available years from the website.

BRIMR's host refuses HTTP clients whose TLS handshake does not look like a
browser's, so requests go through curl_cffi impersonating Chrome.

Features:
    - Thread-safe UI updates
    - One reused HTTP session for all downloads
    - Logging to file
    - Configurable timeouts
    - Cancel button, effective mid-file
    - Cross-platform (Windows, macOS, Linux)

Requirements:
    pip install curl_cffi

Usage:
    python brimr_downloader.py
"""

from __future__ import annotations

import logging
import platform
import queue
import re
import threading
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from urllib.parse import unquote, urljoin, urlparse

from curl_cffi import CurlError
from curl_cffi import requests as curl_requests

if TYPE_CHECKING:
    from tkinter import Event

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# =============================================================================
# Configuration Constants - Adjust these if needed
# =============================================================================

PAGE_TIMEOUT: int = 15
DOWNLOAD_TIMEOUT: int = 90
DOWNLOAD_CHUNK_BYTES: int = 64 * 1024
UI_QUEUE_POLL_MS: int = 100
IMPERSONATE: str = "chrome"

HOME_URL: str = "https://brimr.org/"
BASE_URL_TEMPLATE: str = "https://brimr.org/brimr-rankings-of-nih-funding-in-{year}/"
FIRST_RANKING_YEAR: int = 2006
YEAR_PAGE_RE = re.compile(r"brimr-rankings-of-nih-funding-in-(\d{4})")
EXCEL_SUFFIXES: tuple[str, ...] = (".xls", ".xlsx")
# File signatures: .xlsx is a zip archive, .xls is an OLE compound file.
EXCEL_MAGIC: tuple[bytes, ...] = (b"PK\x03\x04", b"\xd0\xcf\x11\xe0")

FILE_CATEGORIES: dict[str, list[str]] = {
    # Source/master data files - comprehensive institutional data
    "01_Source_Data": [
        "worldwide", "worldwidebrimr", "brimrworldwide",
        "allorgs", "medicalschoolsonly", "medicalschools",
        "contracts", "somcontracts", "worldwidecontractsonly",
    ],
    # School-level rankings
    "02_School_Rankings": [
        "schoolofmedicine",
        "schoolofdentistry", "dentistry",
        "schoolofnursing", "nursing",
        "schoolofpublichealth",
        "schoolofpharmacy", "pharmacy",
        "schoolofveterinarymedicine", "schoolofverterinarymedicine",
        "schoolsofveterinarymedicine", "veterinarymedicine",
        "schoolofosteopathicmedicine",
        "schoolofalliedhealth",
        "hospitals",
        "otherhealthprofessions",
    ],
    # Department summary/rollup files
    "03_Department_Summaries": [
        "bydepartment", "bydepartmentr",
        "awardsbydepartment",
        "medicalschoolsandtheirdepartments",
        "medicalschoolsanddept", "medicalschoolanddept",
        "mastertemplatenihawards", "mastertemplatenihawardsr",
    ],
    # Basic science departments
    "04_Basic_Science": [
        "anatomycellbiol", "anatomycellbiology", "anatomycellbiologyr",
        "biochemistry", "biochemistryr",
        "biomedicalengineering",
        "genetics", "geneticsr",
        "microbiology", "microbiologyr",
        "neurosciences", "neurosciencesr",
        "pharmacology", "pharmacologyr",
        "physiology", "physiologyr",
        "otherbasicsciences",
    ],
    # Clinical departments
    "05_Clinical_Depts": [
        "anesthesiology", "anesthesiologyr",
        "dermatology", "dermatologyr",
        "emergencymedicine", "emergencymediciner",
        "familymedicine", "familymediciner",
        "medicine", "mediciner",
        "neurology", "neurologyr", "neurologyxls",
        "neurosurgery", "neurosurgeryr",
        "nutrition",
        "obgyn", "obgynr",
        "obstetrics", "obstetricsandgynecology", "obstetricsgynecology",
        "ophthalmology", "ophthalmologyr",
        "orthopedics", "orthopedicsr",
        "ent", "otolaryngology", "otolaryngologyr",
        "pathology", "pathologyr",
        "pediatrics", "pediatricsr",
        "physicalme", "physicalmed", "physicalmedicine", "physicalmediciner",
        "psychiatry", "psychiatryr",
        "publichealth", "publichealthr",
        "radiology", "radiologyr",
        "surgery", "surgeryr",
        "urology", "urologyr",
        "otherclinicalsciences",
    ],
    # Principal Investigator rankings
    "06_PI_Rankings": [
        "pi", "allpis", "pisbyrank", "principalinvestigator",
        "allorgdeptpi", "deptorgpi", "deptschoolpi", "deptschoolpir",
        "schooldeptpi",
        "contractspi",
        # Basic science PI files
        "anatomycellbiolpi", "anatomycellbiologypi",
        "biochemistrypi",
        "biomedicalengineeringpi",
        "geneticspi",
        "microbiologypi",
        "neurosciencespi",
        "pharmacologypi", "pharmacologypir",
        "physiologypi", "physiologypi2xls", "physiologypir",
        # Clinical PI files
        "anesthesiologypi",
        "dermatologypi",
        "emergencymedicinepi",
        "familymedicinepi",
        "medicinepi",
        "neurologypi",
        "neurosurgerypi", "neurosurgerypir",
        "obgynpi", "obgynpir",
        "obstetricspi", "obstetricsandgynecologypi", "obstetricsgynecologypi",
        "ophthalmologypi", "ophthalmologypir",
        "orthopedicspi", "orthopedicspir",
        "otolaryngologypi", "otolaryngologypir",
        "pathologypi", "pathologypir",
        "pediatricspi", "pediatricspir",
        "physicalmedicinepi", "physicalmedicinepir",
        "psychiatrypi", "psychiatrypir",
        "publichealthpi", "publichealthpir",
        "radiologypi", "radiologypir",
        "surgerypi", "surgerypir", "surgerypibcorrecte",
        "urologypi", "urologypir",
    ],
    # Geographic analysis files
    "07_Geographic": [
        "state", "statesandcountries",
        "city", "allcities", "citiesbyrankr",
        "institution", "allinstitutions", "allinstitutionsr",
        "organization",
        "fundingrankbystate",
        "percapitafundingbystate", "percapitafundingrankbystate",
    ],
    # Special/other files
    "08_Other": [
        "topten", "toptenr",
        "covidawards", "covid",
        "merit", "nihmerit",
    ],
}


# =============================================================================
# Logging Setup
# =============================================================================


def setup_logging(log_dir: Path) -> logging.Logger:
    """Configure logging to file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"brimr_downloader_{datetime.now():%Y%m%d_%H%M%S}.log"

    logger = logging.getLogger("brimr_downloader")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console_handler)

    logger.info(f"Log file: {log_file}")
    return logger


# =============================================================================
# Cross-Platform Utility Functions
# =============================================================================


def get_downloads_folder() -> Path:
    """Get the user's Downloads folder path (cross-platform)."""
    system = platform.system()

    if system == "Windows":
        import winreg
        try:
            sub_key = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                r"\Explorer\Shell Folders"
            )
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
                downloads = winreg.QueryValueEx(
                    key, "{374DE290-123F-4565-9164-39C4925E467B}"
                )[0]
                return Path(downloads)
        except (OSError, FileNotFoundError):
            pass

    elif system == "Darwin":
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            return downloads

    if system == "Linux":
        try:
            import subprocess
            result = subprocess.run(
                ["xdg-user-dir", "DOWNLOAD"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return Path.home() / "Downloads"


class _AnchorCollector(HTMLParser):
    """Collect anchor hrefs. The parser decodes entities such as &amp; itself."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value and value.strip():
                self.hrefs.append(value.strip())


def collect_hrefs(html: str) -> list[str]:
    """Return every anchor href in the HTML, in document order."""
    collector = _AnchorCollector()
    collector.feed(html)
    collector.close()
    return collector.hrefs


def parse_year_links(html: str) -> list[int]:
    """Return the ranking years linked from a BRIMR page, newest first."""
    years = {
        int(match.group(1))
        for href in collect_hrefs(html)
        if (match := YEAR_PAGE_RE.search(href))
    }
    return sorted(years, reverse=True)


def extract_excel_urls(html: str, page_url: str) -> list[str]:
    """Return absolute Excel URLs linked from a page, in order, without duplicates."""
    urls: list[str] = []
    for href in collect_hrefs(html):
        absolute = urljoin(page_url, href)
        # Test the path, not the whole URL, so query strings do not hide the suffix.
        if urlparse(absolute).path.lower().endswith(EXCEL_SUFFIXES):
            urls.append(absolute)
    return list(dict.fromkeys(urls))


def fallback_years(today: datetime | None = None) -> list[int]:
    """Every year BRIMR could have published, newest first."""
    # BRIMR ranks NIH fiscal years (ending Sept 30), published months later,
    # so the latest possible ranking year is always the prior calendar year.
    latest_possible = (today or datetime.now()).year - 1
    return list(range(latest_possible, FIRST_RANKING_YEAR - 1, -1))


def create_session() -> curl_requests.Session:
    """Create an HTTP session whose TLS handshake matches Chrome's."""
    return curl_requests.Session(impersonate=IMPERSONATE)


def fetch_page(session: curl_requests.Session, url: str) -> str:
    """Return a page's HTML. Raises CurlError on network or HTTP failure."""
    resp = session.get(url, timeout=PAGE_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def detect_available_years(
    session: curl_requests.Session, logger: logging.Logger | None = None
) -> tuple[list[int], bool]:
    """
    Read the available ranking years from the BRIMR homepage navigation.

    Returns (years, detected); detected is False when the page could not be
    read and the fallback range is returned instead.
    """
    try:
        years = parse_year_links(fetch_page(session, HOME_URL))
    except CurlError as e:
        years = []
        if logger:
            logger.debug(f"Homepage read failed: {e}")

    if years:
        if logger:
            logger.info(
                f"Found {len(years)} years from homepage: "
                f"{min(years)}-{max(years)}"
            )
        return years, True

    fallback = fallback_years()
    if logger:
        logger.warning(
            f"Year detection failed, using range "
            f"{min(fallback)}-{max(fallback)}"
        )
    return fallback, False


def categorize_file(filename: str) -> str:
    """Determine the category folder for a file based on its name."""
    raw = filename.lower()
    norm = raw.replace("-", "").replace("_", "")

    # Check PI files first (they often contain department names too)
    if "pi" in norm:
        # Check patterns that need underscores/hyphens preserved
        if any(tag in raw for tag in ["_pi_", "_pi.", "pi_2", "contractspi"]):
            return "06_PI_Rankings"
        # Check normalized patterns
        if any(tag in norm for tag in ["allorgdeptpi", "deptschoolpi", "schooldeptpi"]):
            return "06_PI_Rankings"

    # Build list of (pattern, category) sorted by pattern length descending
    # This ensures longer/more specific patterns match first
    all_patterns: list[tuple[str, str]] = []
    for category, patterns in FILE_CATEGORIES.items():
        if category == "06_PI_Rankings":
            continue
        for pattern in patterns:
            clean_pattern = pattern.replace("-", "").replace("_", "")
            all_patterns.append((clean_pattern, category))

    # Sort by pattern length descending (longest first)
    all_patterns.sort(key=lambda x: len(x[0]), reverse=True)

    for pattern, category in all_patterns:
        if pattern in norm:
            return category

    return "09_Uncategorized"


def sanitize_filename(filename: str) -> str:
    """Sanitize filename by removing query strings and invalid characters."""
    # Remove query string
    if "?" in filename:
        filename = filename.split("?", 1)[0]
    # Replace characters invalid on Windows and generally unsafe
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        filename = filename.replace(ch, "_")
    # Trim whitespace and trailing dots (Windows quirk)
    return filename.strip().strip(".")


# =============================================================================
# File Downloads
# =============================================================================


class DownloadError(Exception):
    """A file could not be downloaded or was not a valid Excel file."""


class DownloadCancelled(Exception):
    """The user cancelled while a file was transferring."""


def download_file(
    session: curl_requests.Session,
    url: str,
    final_path: Path,
    cancel_event: threading.Event | None = None,
) -> int:
    """
    Stream a file to final_path and return its size in bytes.

    The body goes to a .part file first and is renamed only once it is
    complete and verified, so a failed or cancelled transfer never leaves a
    file that the skip-existing check would later mistake for a finished one.
    """
    part_path = final_path.with_name(final_path.name + ".part")
    final_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = session.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True)
    except CurlError as e:
        raise DownloadError(f"request failed: {e}") from e

    written = 0
    try:
        if resp.status_code != 200:
            raise DownloadError(f"HTTP {resp.status_code}")

        with part_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if cancel_event and cancel_event.is_set():
                    raise DownloadCancelled
                if not chunk:
                    continue
                # A blocked request can return an HTML page with status 200,
                # so check the signature before saving anything as Excel.
                if written == 0 and not chunk.startswith(EXCEL_MAGIC):
                    ctype = resp.headers.get("Content-Type", "unknown type")
                    raise DownloadError(f"not an Excel file ({ctype})")
                fh.write(chunk)
                written += len(chunk)

        expected = resp.headers.get("Content-Length", "")
        # With compression the header counts encoded bytes, so skip the check.
        encoded = resp.headers.get("Content-Encoding", "identity") != "identity"
        if written == 0:
            raise DownloadError("empty response")
        if expected.isdigit() and not encoded and int(expected) != written:
            raise DownloadError(f"incomplete ({written} of {expected} bytes)")

        part_path.replace(final_path)
        return written

    except CurlError as e:
        raise DownloadError(f"transfer failed: {e}") from e

    finally:
        resp.close()
        part_path.unlink(missing_ok=True)
        if not final_path.exists():
            try:
                final_path.parent.rmdir()  # Succeeds only if nothing else is there
            except OSError:
                pass


# =============================================================================
# GUI Application
# =============================================================================


class BRIMRDownloaderApp:
    """Thread-safe GUI application for downloading BRIMR NIH Funding Excel files."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BRIMR NIH Funding Downloader")
        self.root.geometry("620x780")
        self.root.resizable(True, True)

        self.downloads_folder: Path = get_downloads_folder()
        self.output_folder: Path = self.downloads_folder / "BRIMR_Data"
        self.year_vars: dict[int, tk.BooleanVar] = {}
        self.available_years: list[int] = []
        self.is_downloading: bool = False

        self.ui_queue: queue.Queue[tuple[Callable, tuple]] = queue.Queue()
        self.cancel_event: threading.Event = threading.Event()
        self.logger: logging.Logger | None = None

        self._setup_ui()
        self._start_ui_queue_polling()
        self._detect_years_async()

    # -------------------------------------------------------------------------
    # Thread-Safe UI Updates
    # -------------------------------------------------------------------------

    def _start_ui_queue_polling(self) -> None:
        self._drain_ui_queue()

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                fn, args = self.ui_queue.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(UI_QUEUE_POLL_MS, self._drain_ui_queue)

    def _enqueue_ui(self, fn: Callable, *args) -> None:
        self.ui_queue.put((fn, args))

    def _update_status(self, message: str, detail: str = "") -> None:
        def apply():
            self.status_label.config(text=message)
            self.detail_label.config(text=detail)
        self._enqueue_ui(apply)

    def _update_progress(self, value: int, maximum: int) -> None:
        def apply():
            self.progress_bar["maximum"] = maximum
            self.progress_bar["value"] = value
        self._enqueue_ui(apply)

    def _show_info(self, title: str, message: str) -> None:
        self._enqueue_ui(lambda: messagebox.showinfo(title, message))

    def _show_error(self, title: str, message: str) -> None:
        self._enqueue_ui(lambda: messagebox.showerror(title, message))

    def _set_buttons_state(self, downloading: bool) -> None:
        def apply():
            self.download_btn.config(state="disabled" if downloading else "normal")
            self.cancel_btn.config(state="normal" if downloading else "disabled")
        self._enqueue_ui(apply)

    # -------------------------------------------------------------------------
    # UI Setup
    # -------------------------------------------------------------------------

    def _setup_ui(self) -> None:
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        self._create_header(main_frame)
        self._create_folder_info(main_frame)
        self._create_year_selection(main_frame)
        self._create_options(main_frame)
        self._create_progress_section(main_frame)
        self._create_buttons(main_frame)

    def _create_header(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent, text="BRIMR NIH Funding Data Downloader",
            font=("Segoe UI", 14, "bold"),
        ).pack(pady=(0, 5))

        ttk.Label(
            parent, text="Downloads Excel files directly from brimr.org",
            font=("Segoe UI", 10),
        ).pack(pady=(0, 5))

        ttk.Label(
            parent, text=f"Platform: {platform.system()} {platform.machine()}",
            font=("Segoe UI", 8, "italic"), foreground="gray",
        ).pack(pady=(0, 10))

    def _create_folder_info(self, parent: ttk.Frame) -> None:
        folder_frame = ttk.Frame(parent)
        folder_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            folder_frame, text="Save to:", font=("Segoe UI", 9)
        ).pack(side=tk.LEFT)

        self.folder_label = ttk.Label(
            folder_frame, text=str(self.output_folder),
            font=("Segoe UI", 9, "italic"), foreground="gray",
        )
        self.folder_label.pack(side=tk.LEFT, padx=(5, 10))

        ttk.Button(
            folder_frame, text="Change...",
            command=self._change_output_folder, width=10,
        ).pack(side=tk.LEFT)

    def _change_output_folder(self) -> None:
        folder = filedialog.askdirectory(
            initialdir=self.output_folder, title="Select Output Folder"
        )
        if folder:
            self.output_folder = Path(folder)
            self.folder_label.config(text=str(self.output_folder))

    def _create_year_selection(self, parent: ttk.Frame) -> None:
        self.years_frame = ttk.LabelFrame(
            parent, text="Select Years (detecting...)", padding="10"
        )
        self.years_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        btn_frame = ttk.Frame(self.years_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(
            btn_frame, text="Select All", command=self._select_all
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(
            btn_frame, text="Deselect All", command=self._deselect_all
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(
            btn_frame, text="Recent 5 Years", command=self._select_recent_5
        ).pack(side=tk.LEFT)

        self.canvas = tk.Canvas(self.years_frame, height=180)
        scrollbar = ttk.Scrollbar(
            self.years_frame, orient="vertical", command=self.canvas.yview
        )
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._bind_mousewheel()

        self.loading_label = ttk.Label(
            self.scrollable_frame,
            text="Detecting available years from BRIMR website...",
            font=("Segoe UI", 9, "italic"),
        )
        self.loading_label.pack(pady=20)

    def _bind_mousewheel(self) -> None:
        system = platform.system()
        if system == "Linux":
            self.canvas.bind_all(
                "<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units")
            )
            self.canvas.bind_all(
                "<Button-5>", lambda e: self.canvas.yview_scroll(1, "units")
            )
        else:
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event: Event) -> None:
        if platform.system() == "Darwin":
            delta = -1 * event.delta
        else:
            delta = -1 * (event.delta // 120)
        self.canvas.yview_scroll(int(delta), "units")

    def _detect_years_async(self) -> None:
        def detect():
            years, detected = fallback_years(), False
            try:
                session = create_session()
                try:
                    years, detected = detect_available_years(session)
                finally:
                    session.close()
            except Exception:
                # Any failure here must still reach the UI, or the year list
                # stays on "Detecting..." forever. The fallback keeps it usable.
                pass
            self._enqueue_ui(self._populate_years, years, detected)
        threading.Thread(target=detect, daemon=True).start()

    def _populate_years(self, years: list[int], detected: bool) -> None:
        self.available_years = years
        self.loading_label.destroy()

        year_range = f"{min(years)}-{max(years)}" if years else "None found"
        if detected:
            label = f"Select Years ({year_range} available)"
        else:
            label = f"Select Years ({year_range}, default range: BRIMR not reached)"
        self.years_frame.configure(text=label)

        for i, year in enumerate(years):
            var = tk.BooleanVar(value=False)
            self.year_vars[year] = var
            cb = ttk.Checkbutton(
                self.scrollable_frame, text=str(year), variable=var, width=8
            )
            cb.grid(row=i // 5, column=i % 5, sticky="w", padx=5, pady=2)

        self.scrollable_frame.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _create_options(self, parent: ttk.Frame) -> None:
        options_frame = ttk.LabelFrame(parent, text="Options", padding="10")
        options_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            options_frame,
            text="Files organized: Year → Category → Files | Logs saved with downloads",
            font=("Segoe UI", 8, "italic"), foreground="gray",
        ).pack(anchor="w")

    def _create_progress_section(self, parent: ttk.Frame) -> None:
        progress_frame = ttk.LabelFrame(parent, text="Progress", padding="10")
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.status_label = ttk.Label(progress_frame, text="Ready to download")
        self.status_label.pack(anchor="w")

        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(5, 0))

        self.detail_label = ttk.Label(progress_frame, text="", font=("Segoe UI", 8))
        self.detail_label.pack(anchor="w", pady=(5, 0))

    def _create_buttons(self, parent: ttk.Frame) -> None:
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(0, 5))

        style = ttk.Style()
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        self.download_btn = ttk.Button(
            btn_frame, text="Download Selected Years",
            command=self._start_download, style="Accent.TButton",
        )
        self.download_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.cancel_btn = ttk.Button(
            btn_frame, text="Cancel",
            command=self._cancel_download, state="disabled",
        )
        self.cancel_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # -------------------------------------------------------------------------
    # Selection Helpers
    # -------------------------------------------------------------------------

    def _select_all(self) -> None:
        for var in self.year_vars.values():
            var.set(True)

    def _deselect_all(self) -> None:
        for var in self.year_vars.values():
            var.set(False)

    def _select_recent_5(self) -> None:
        self._deselect_all()
        for year in self.available_years[:5]:
            if year in self.year_vars:
                self.year_vars[year].set(True)

    def _get_selected_years(self) -> list[int]:
        return [year for year, var in self.year_vars.items() if var.get()]

    # -------------------------------------------------------------------------
    # Download Control
    # -------------------------------------------------------------------------

    def _start_download(self) -> None:
        selected_years = self._get_selected_years()

        if not selected_years:
            messagebox.showwarning("No Selection", "Please select at least one year.")
            return

        if self.is_downloading:
            return

        year_str = ", ".join(str(y) for y in sorted(selected_years, reverse=True))

        if not messagebox.askyesno(
            "Confirm Download",
            f"Download Excel files for: {year_str}?\n\n"
            f"Files will be saved to:\n{self.output_folder}"
        ):
            return

        self.logger = setup_logging(self.output_folder)
        self.logger.info(f"Starting download for years: {year_str}")

        self.is_downloading = True
        self.cancel_event.clear()
        self._set_buttons_state(downloading=True)

        threading.Thread(
            target=self._download_years, args=(selected_years,), daemon=True
        ).start()

    def _cancel_download(self) -> None:
        if self.is_downloading:
            self.cancel_event.set()
            self._update_status("Cancelling...", "Stopping the current file")
            if self.logger:
                self.logger.info("Cancel requested by user")

    def _download_years(self, years: list[int]) -> None:
        """Download Excel files for the selected years over one HTTP session."""
        downloaded = 0
        skipped = 0
        failed = 0
        years_skipped = 0  # Years with no data or failed to load
        cancelled = False

        self.output_folder.mkdir(parents=True, exist_ok=True)
        session: curl_requests.Session | None = None

        try:
            session = create_session()

            for year in sorted(years):  # Oldest to newest
                if self.cancel_event.is_set():
                    cancelled = True
                    break

                year_folder = self.output_folder / str(year)
                url = BASE_URL_TEMPLATE.format(year=year)
                self._update_status(f"Loading {year} page...", url)
                if self.logger:
                    self.logger.info(f"Processing year {year}")

                try:
                    excel_urls = extract_excel_urls(fetch_page(session, url), url)
                except CurlError as e:
                    if self.logger:
                        self.logger.error(f"Failed to load {year}: {e}")
                    self._update_status(f"⚠ {year}: Page failed to load", str(e)[:50])
                    years_skipped += 1
                    time.sleep(1)  # Brief pause so user sees the message
                    continue

                if self.logger:
                    self.logger.debug(
                        f"Found {len(excel_urls)} unique Excel URLs for {year}"
                    )

                if not excel_urls:
                    self._update_status(
                        f"⚠ {year}: No Excel files found", "Skipping this year"
                    )
                    if self.logger:
                        self.logger.warning(f"No Excel files found for {year}")
                    years_skipped += 1
                    time.sleep(1)  # Brief pause so user sees the message
                    continue

                year_folder.mkdir(exist_ok=True)
                self._update_status(
                    f"Found {len(excel_urls)} files for {year}", "Starting..."
                )
                if self.logger:
                    self.logger.info(f"Found {len(excel_urls)} files for {year}")

                for i, file_url in enumerate(excel_urls, 1):
                    if self.cancel_event.is_set():
                        cancelled = True
                        break

                    raw_name = unquote(Path(urlparse(file_url).path).name)
                    filename = sanitize_filename(raw_name)
                    category = categorize_file(filename)
                    final_path = year_folder / category / filename

                    if final_path.exists():
                        skipped += 1
                        self._update_status(
                            f"{year}: {i}/{len(excel_urls)}",
                            f"⏭ Exists: {category}/{filename}"
                        )
                        self._update_progress(i, len(excel_urls))
                        continue

                    self._update_status(
                        f"Downloading {year}: {i}/{len(excel_urls)}", f"→ {filename}"
                    )
                    self._update_progress(i, len(excel_urls))

                    try:
                        size = download_file(
                            session, file_url, final_path, self.cancel_event
                        )
                    except DownloadCancelled:
                        cancelled = True
                        break
                    except (DownloadError, OSError) as e:
                        failed += 1
                        if self.logger:
                            self.logger.warning(f"⚠ Failed: {filename}: {e}")
                        continue

                    downloaded += 1
                    if self.logger:
                        self.logger.info(
                            f"✓ {category}/{filename} ({size / 1024:.0f} KB)"
                        )
                    self._update_status(
                        f"{year}: {i}/{len(excel_urls)}",
                        f"✓ {category}/{filename}"
                    )

                if cancelled:
                    break

        except Exception as e:
            if self.logger:
                self.logger.exception("Fatal error")
            self._show_error("Error", f"An error occurred:\n{e}")

        finally:
            if session:
                session.close()

            self.is_downloading = False
            self._set_buttons_state(downloading=False)

            summary = (
                f"Downloaded: {downloaded} | Existed: {skipped} | "
                f"Failed: {failed} | Years without data: {years_skipped}"
            )

            if cancelled:
                self._update_status("⚠ Download cancelled", summary)
                self._show_info("Cancelled", f"Download cancelled.\n\n{summary}")
            else:
                self._update_status("✓ Download complete!", summary)
                self._update_progress(100, 100)
                self._show_info(
                    "Complete",
                    f"Downloaded {downloaded} files!\n"
                    f"Already existed: {skipped}\n"
                    f"Failed: {failed}\n"
                    f"Years without data: {years_skipped}\n\n"
                    f"Files saved to:\n{self.output_folder}"
                )

            if self.logger:
                self.logger.info(f"Finished. {summary}")


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> None:
    root = tk.Tk()
    root.geometry("620x780")

    if platform.system() == "Windows":
        try:
            root.iconbitmap(default="")
        except tk.TclError:
            pass

    BRIMRDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()