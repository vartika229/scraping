# Google Maps Scraper

A Python-based Playwright scraping script that extracts structured business data from Google Maps given a search results URL or a single business listing URL. Supported export formats are CSV, JSON, and Excel (.xlsx).

## Requirements

- Python 3.10+
- (Optional but recommended) Docker

## Setup (Local)

1. Clone or download this directory.
2. Install Python requirements:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

## Setup (Docker)

To run the scraper without installing Playwright and Chromium on your host machine, you can build and run it using the Docker environment.

1. Build the image:
   ```bash
   docker build -t gmaps-scraper .
   ```

## Usage

### Interactive Mode (Recommended)

Simply run the script without any arguments. You will be guided through the setup:

```bash
python google_maps_scraper.py
```

The interactive mode will prompt you to:
1. Paste a Google Maps URL (search results or business listing)
2. Choose an output format (CSV, JSON, or Excel)
3. Set the output file name
4. Configure max results (for search URLs)
5. Opt-in to email extraction
6. Show/hide the browser window

### CLI Mode

You can also pass arguments directly for scripted / automated usage:

```bash
# Basic Search Mode (Exports to CSV by default)
python google_maps_scraper.py --url "https://www.google.com/maps/search/coffee+shops+in+austin" --output results.csv --max 20

# With Email Extraction and Excel Output
python google_maps_scraper.py --url "https://www.google.com/maps/search/plumbers+in+london" --output results.xlsx --format xlsx --max 10 --emails

# Single Listing Mode (Auto-detected based on URL format)
python google_maps_scraper.py --url "https://www.google.com/maps/place/..." --output single_place.json --format json --emails
```

### Docker Usage

When using Docker, you need to mount a local directory to `/app/output` so you can retrieve your generated CSV/JSON/XLSX files. 

Assuming you are in the project directory:

```bash
docker run --rm -v "$(pwd)/output:/app/output" gmaps-scraper --url "https://www.google.com/maps/search/coffee+shops+in+austin" --output /app/output/results.csv --max 5
```

### Argument Reference

| Argument | Description | Required | Default |
|---|---|---|---|
| `--url` | The Google Maps search or place URL | No (interactive mode if omitted) | None |
| `--output` | The filename to save the extracted data | No | `scraped_data.<format>` |
| `--format` | Data format: `csv`, `json`, or `xlsx` | No | `csv` |
| `--max` | Limit the number of business results returned (search mode) | No | 20 |
| `--emails` | Flag to enable scraping the business website for emails | No | False |
| `--visible` | Open local browser window (Not recommended for Docker) | No | False |

## Output Fields

- **Company Name**: Business name as shown on Maps
- **Phone Number**: Primary contact string
- **Email**: Extracted via regex if `--emails` is used
- **Website**: Official website link
- **Rating**: Numerical rating
- **Review Count**: Review volume
- **Category**: Main Google Maps category
- **Address**: Text string form
- **Google Maps URL**: Direct Place Listing Link
