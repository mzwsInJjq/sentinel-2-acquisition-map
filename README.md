# Sentinel-2 Acquisition Plan KML Downloader & Visualizer

This Python script automates the process of fetching, downloading, and visualizing the latest Sentinel-2 satellite acquisition plan KML files from the Copernicus website. It supports Sentinel-2A, Sentinel-2B, and Sentinel-2C, and provides geospatial querying and visualization capabilities.

## Features
- **Automatic KML Discovery:** Scrapes the Copernicus Sentinel-2 acquisition plans page to find the latest KML download links for each satellite.
- **Efficient Downloading:** Uses `curl` for fast downloads and skips files that are already present locally.
- **Multi-layer KML Handling:** Loads only the primary 'NOMINAL' layer from KML files to avoid warnings.
- **GeoDataFrame Integration:** Loads KMLs into GeoPandas GeoDataFrames for easy geospatial analysis.
- **Timestamp Extraction:** Parses each KML to extract the `<begin>` timestamp for each acquisition plan and adds it as a column.
- **Location Query:** Given a latitude and longitude, prints all acquisition plans (with ID and timestamp) that pass over the location for each satellite.
- **Visualization:** Plots all three satellites' acquisition plans on a map using Matplotlib, with color-coded overlays.

## Requirements
- Python 3.8+
- [GeoPandas](https://geopandas.org/)
- [Fiona](https://fiona.readthedocs.io/)
- [Matplotlib](https://matplotlib.org/)
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)
- [lxml](https://lxml.de/)
- [requests](https://docs.python-requests.org/)
- `curl` (must be available in your system PATH)

Install dependencies with:
```sh
pip install geopandas fiona matplotlib beautifulsoup4 lxml requests
```

## Usage
1. **Rename the script if needed:**
   Ensure the script is named `sentinel_2_acq.py` (underscores, not dashes) for import compatibility.

2. **Run the script:**
   ```sh
   python sentinel_2_acq.py
   ```
   The script will:
   - Fetch the latest KML links
   - Download KMLs (if not already present)
   - Parse and load them into GeoDataFrames
   - Query a sample location (default: Seattle, WA)
   - Print all acquisition plans passing over that location (with ID and timestamp)
   - Display a map overlay of all three satellites' acquisition plans

3. **Change the query location:**
   Edit the `location_name, lat, lon` variables in the `__main__` block to query a different location.

## Example Output
```
Querying acquisition plans for Seattle, WA (47.6062, -122.3321)
Sentinel-2A:
  51948-2\t2025-06-03T19:37:18.057
  52134-2\t2025-06-10T19:37:18.057
Sentinel-2B:
  43082-1\t2025-06-04T19:37:18.057
  ...
Sentinel-2C:
  3844-1\t2025-06-05T19:37:18.057
  ...
```

## Notes
- Only the 'NOMINAL' layer of each KML is loaded by default.
- The script is designed for Windows but should work on Linux/Mac with minor adjustments (ensure `curl` is available).
- If you want to use this as a module, import as `import sentinel_2_acq` (not with dashes).

## License
MIT License

## Acknowledgments
- [Copernicus Sentinel-2 Mission](https://sentinels.copernicus.eu/web/sentinel/missions/sentinel-2)
- [GeoPandas](https://geopandas.org/)
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/)
