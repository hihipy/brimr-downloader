# BRIMR Downloader

[![Link Check](https://github.com/hihipy/brimr-downloader/actions/workflows/links.yml/badge.svg)](https://github.com/hihipy/brimr-downloader/actions/workflows/links.yml)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

**Built with**

[![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Selenium](https://img.shields.io/badge/Selenium-43B02A?style=flat&logo=selenium&logoColor=white)](https://selenium.dev)
[![Tkinter](https://img.shields.io/badge/Tkinter-FFD43B?style=flat&logo=python&logoColor=black)](https://docs.python.org/3/library/tkinter.html)

If you've ever spent time downloading Excel files from the BRIMR website one by one, you know how tedious it gets. This Python script automates that work so you can get straight to analyzing NIH funding data, turning hours of clicking into a single organized download.

---

## The Problem

The [Blue Ridge Institute for Medical Research (BRIMR)](https://brimr.org/) publishes excellent NIH funding rankings, but getting the data out is a chore:

- **Manual downloads:** Each Excel file has to be downloaded individually, and there are 70+ files per year across nearly two decades of data.
- **No organization:** Files arrive with inconsistent names and no folder structure, leaving a mess in your Downloads folder.
- **Time-consuming:** Downloading even five years of data by hand can take an hour or more of repetitive clicking.
- **Easy to miss files:** With so many links on each page, it's easy to skip files or grab duplicates.

---

## The Solution

This script uses browser automation to visit each year's BRIMR page, download every Excel file, and sort them into a clean folder structure.

### Why Browser Automation?

BRIMR's server turns away requests that don't come from a real web browser, so a plain download script gets blocked. This tool drives an actual copy of Chrome, which the server accepts.

- **Gets past the server check:** Requests from ordinary scripts are refused. A real browser is let through.
- **Reliable downloads:** Automating a real browser means downloads work the same way they would if you clicked each link yourself.
- **Desktop GUI:** No command line required. Check the years you want and click Download.

---

## Features

- **Simple GUI:** A desktop interface to select years and watch progress.
- **Single Chrome instance:** Reuses one browser session for all downloads, which speeds up multi-year runs.
- **Automatic sorting:** Files are categorized into logical folders (School Rankings, Clinical Departments, PI Rankings, and so on).
- **Skips existing files:** Won't re-download files you already have, which makes adding new years easy.
- **Cancel anytime:** Stop mid-download without losing what's already saved.
- **Logging:** Every download is recorded to a timestamped file for debugging.

---

## Getting Started

### You'll Need Python and Chrome

Install **Python 3.10** or newer from the official [Python website](https://www.python.org/), and make sure [Google Chrome](https://www.google.com/chrome/) is installed.

### Running the Downloader

1. **Set up your environment:**

   Open your terminal or command prompt, navigate to the project folder, and run:

   **macOS / Linux:**

```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install selenium
```

   **Windows:**

```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install selenium
```

2. **Run the script:**

```bash
   python brimr_downloader.py
```

3. **Select your years:**

   When the window opens, the app starts a hidden copy of Chrome to read the available years from the BRIMR website. This takes a few seconds. Check the years you want, or use "Select All" / "Recent 5 Years."

4. **Download:**

   Hit the Download button and watch the progress bar. Your files will be organized and ready when it finishes.

---

## Output Structure

The downloader builds an organized folder structure in your Downloads folder.

| Folder / File                                  | Description                                                                        |
| ---------------------------------------------- | ---------------------------------------------------------------------------------- |
| `BRIMR_Data/`                                  | Root folder containing all downloaded files, organized by year.                    |
| `BRIMR_Data/2024/`                             | Each selected year gets its own folder.                                            |
| `BRIMR_Data/2024/01_Source_Data/`              | Worldwide rankings, contracts, and full institutional data.                        |
| `BRIMR_Data/2024/02_School_Rankings/`          | Medical schools, nursing, pharmacy, dentistry, and other school types.             |
| `BRIMR_Data/2024/03_Department_Summaries/`     | Aggregated views of funding by department.                                         |
| `BRIMR_Data/2024/04_Basic_Science/`            | Biochemistry, genetics, neurosciences, pharmacology, and more.                     |
| `BRIMR_Data/2024/05_Clinical_Depts/`           | Medicine, surgery, pediatrics, psychiatry, and 20+ specialties.                    |
| `BRIMR_Data/2024/06_PI_Rankings/`              | Individual researcher rankings by department and institution.                      |
| `BRIMR_Data/2024/07_Geographic/`               | Rankings by state, city, and institution location.                                 |
| `BRIMR_Data/2024/08_Other/`                    | Top Ten lists, COVID awards, MERIT awards, and other datasets.                     |
| `brimr_downloader_*.log`                       | Timestamped log of every file downloaded.                                          |

---

## Options

| Option             | Description                                                      |
| ------------------ | ---------------------------------------------------------------- |
| **Output Folder**  | Change where files are saved (defaults to Downloads/BRIMR_Data). |
| **Headless Mode**  | Run Chrome invisibly in the background (off by default).         |
| **Year Selection** | Check individual years or use the quick-select buttons.          |

---

## Troubleshooting

**Chrome doesn't start / ChromeDriver error**
Selenium finds the matching ChromeDriver for your Chrome version on its own. Make sure Google Chrome is installed, Selenium is version 4.6 or newer, and your internet connection is working.

**The year list says "default range"**
The app couldn't reach BRIMR when it started, so it lists every possible year since 2006 instead. Check your connection and restart the app.

**Some years show no files**
BRIMR data has a natural lag, so the most recent year may not be posted yet. The script reports "Years without data: X" if any selected years are empty.

**Download seems stuck**
Larger files take longer. Check the log file for progress, or turn off headless mode to watch the browser work.

---

## Requirements

- Python 3.10+
- Google Chrome
- Internet connection

**Python Packages:**
- `selenium` (4.6 or newer) - Browser automation and ChromeDriver setup

---

## License

This project is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

You are free to:
- Use, share, and adapt this work
- Use it at your job

Under these terms:
- **Attribution:** Credit the original author
- **NonCommercial:** No selling or commercial products
- **ShareAlike:** Derivatives must use the same license
