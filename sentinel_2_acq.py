import requests
from bs4 import BeautifulSoup
import os
import re
import fiona
import subprocess
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import xml.etree.ElementTree as ET
from mpl_toolkits.basemap import Basemap

# Define the URL of the Sentinel-2 Acquisition Plans page
ACQUISITION_PLANS_URL = "https://sentinels.copernicus.eu/web/sentinel/copernicus/sentinel-2/acquisition-plans"
BASE_URL = "https://sentinels.copernicus.eu/documents/d/sentinel/"

output_directory = "sentinel_kml_data"
os.makedirs(output_directory, exist_ok=True)

def fetch_latest_kml_links(url):
    """
    Fetches the HTML content of the acquisition plans page and extracts
    the URLs of the latest KML files for Sentinel-2A, 2B, and 2C.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        soup = BeautifulSoup(response.text, 'html.parser')

        latest_kml_links = {}

        # The structure of the page has H4 tags for each satellite (Sentinel-2A, 2B, 2C)
        # followed by a list of links. We want the first link in each list.

        satellites = ["Sentinel-2A", "Sentinel-2B", "Sentinel-2C"]

        # DEBUG: Print all h4 tags to understand the structure of the page
        """
        for h4 in soup.find_all('h4'):
            print(f"Found H4 tag: `{h4.text}`")
        exit()
        """

        for satellite_name in satellites:
            # Find the H4 tag for the current satellite
            h4_tag = None
            for h4 in soup.find_all('h4'):
                if h4.text.strip() == satellite_name:
                    h4_tag = h4
                    break
            if h4_tag:
                # Find the immediate sibling ul (unordered list)
                ul_tag = h4_tag.find_next_sibling('ul')
                if ul_tag:
                    # Get the first list item (li) and then the anchor tag (a) within it
                    first_li = ul_tag.find('li')
                    if first_li:
                        link_tag = first_li.find('a', href=True)
                        if link_tag:
                            full_kml_url = link_tag['href']
                            # Extract just the filename from the URL
                            filename_match = re.search(r'documents/d/sentinel/(.*)', full_kml_url)
                            if filename_match:
                                filename = filename_match.group(1)
                                latest_kml_links[satellite_name] = filename
                            else:
                                print(f"Could not extract filename from URL: {full_kml_url}")
                        else:
                            print(f"No link found in the first list item for {satellite_name}.")
                    else:
                        print(f"No list items found for {satellite_name}.")
                else:
                    print(f"No unordered list found after {satellite_name} heading.")
            else:
                print(f"Could not find heading for {satellite_name}.")
        return latest_kml_links

    except requests.exceptions.RequestException as e:
        print(f"Error fetching the acquisition plans page: {e}")
        return {}
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return {}

def download_and_parse_kml(satellite_name, kml_filename, output_dir):
    """
    Downloads a KML file using curl. If the file already exists, it will not be redownloaded.
    Loads the KML file as a GeoDataFrame using geopandas and fiona, loading all layers.
    """
    kml_url = f"{BASE_URL}{kml_filename}"
    local_filepath = os.path.join(output_dir, f"{kml_filename}.kml")

    if os.path.exists(local_filepath):
        print(f"\n{satellite_name}: {local_filepath} already exists, skipping download.")
    else:
        print(f"\nDownloading {satellite_name} KML from: {kml_url}")
        try:
            # Use curl for faster download
            result = subprocess.run([
                "curl", "-L", "-sS", "-o", local_filepath, kml_url
            ], check=True)
            print(f"Downloaded {satellite_name} KML to: {local_filepath}")
        except subprocess.CalledProcessError as e:
            print(f"Error downloading {satellite_name} KML with curl: {e}")
            return None

    try:
        # Load all layers from the KML file
        fiona.drvsupport.supported_drivers['KML'] = 'rw'
        layers = fiona.listlayers(local_filepath)
        gdf_list = []
        
        for layer in layers:
            # Skip layers that do not start with 'NOMINAL'
            # This is to avoid loading layers that are not relevant acquisition plans
            if not layer.startswith('NOMINAL'):
                continue
            gdf = gpd.read_file(local_filepath, layer=layer)
            gdf_list.append(gdf)
        gdf = pd.concat(gdf_list, ignore_index=True)

        gdf = add_begin_timestamp_to_gdf(local_filepath, gdf)
        print(f"Loaded {satellite_name} KML as GeoDataFrame with {len(gdf)} features.")
        return gdf
    except Exception as e:
        print(f"Error reading KML for {satellite_name} with geopandas/fiona: {e}")
        return None

def add_begin_timestamp_to_gdf(kml_path, gdf):
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    tree = ET.parse(kml_path)
    root = tree.getroot()
    placemarks = root.findall('.//kml:Placemark', ns)
    name_to_begin = {}
    for pm in placemarks:
        name_elem = pm.find('kml:name', ns)
        timespan_elem = pm.find('kml:TimeSpan', ns)
        begin_elem = timespan_elem.find('kml:begin', ns) if timespan_elem is not None else None
        if name_elem is not None and begin_elem is not None:
            name_to_begin[name_elem.text] = begin_elem.text
    # Add the 'begin' column to the GeoDataFrame
    if 'Name' in gdf.columns:
        gdf['begin'] = gdf['Name'].map(name_to_begin)
    elif 'name' in gdf.columns:
        gdf['begin'] = gdf['name'].map(name_to_begin)
    return gdf

def find_acq_plans_over_location(lat, lon, kml_data_objects):
    """
    Given a latitude and longitude, print which acquisition plans (by satellite) pass over the location.
    Each matching acquisition plan is displayed on one line like a pandas dataframe row, showing ID and 'begin' timestamp.
    """
    from shapely.geometry import Point
    point = Point(lon, lat)
    found = False
    for satellite, gdf in kml_data_objects.items():
        # Check if any geometry in the GeoDataFrame contains the point
        matches = gdf[gdf.geometry.contains(point)]
        if not matches.empty:
            found = True
            print(f"{satellite}:")
            # Find the ID and begin columns
            id_col = None
            for col in ["Name", "name", "ID", "id"]:
                if col in matches.columns:
                    id_col = col
                    break
            begin_col = "begin" if "begin" in matches.columns else None
            # Print each row on one line, showing ID and begin timestamp if available
            for idx, row in matches.iterrows():
                id_val = row[id_col] if id_col else "<no id>"
                begin_val = row[begin_col] if begin_col else "<no begin>"
                print(f"  {id_val}\t{begin_val}")
    if not found:
        print(f"No acquisition plan passes over ({lat}, {lon}) for any satellite.")

if __name__ == "__main__":
    print(f"Fetching latest KML links from: {ACQUISITION_PLANS_URL}")
    latest_kml_filenames = fetch_latest_kml_links(ACQUISITION_PLANS_URL)

    kml_data_objects = {}

    if latest_kml_filenames:
        print("\n--- Latest KML Filenames Found ---")
        for satellite, filename in latest_kml_filenames.items():
            print(f"{satellite}: {filename}")

        print("\n--- Downloading and Parsing KML Files ---")
        for satellite, filename in latest_kml_filenames.items():
            kml_object = download_and_parse_kml(satellite, filename, output_directory)
            if kml_object is not None:
                kml_data_objects[satellite] = kml_object

        print("\n--- KML Data Objects Loaded ---")
        for satellite, kml_object in kml_data_objects.items():
            print(f"{satellite}: {type(kml_object).__name__} object loaded.")
            # Print unique names from the KML features if available
            """
            if "Name" in kml_object.columns:
                print(f"  Document Names: {kml_object['Name'].unique()}")
            elif "name" in kml_object.columns:
                print(f"  Document Names: {kml_object['name'].unique()}")
            else:
                print("  No 'Name' or 'name' column found in GeoDataFrame.")
            """

        # --- Query acquisition plans for target location(s) before plotting ---
        # Examples: 
        # 1. Seattle, WA (47.6062, -122.3321)
        # 2. New York, NY (40.7143, -74.0060)
        # 3. Chicago, IL (41.8500, -87.6500)
        locations = {
            "Seattle, WA": (47.6062, -122.3321),
            "New York, NY": (40.7143, -74.0060),
            "Chicago, IL": (41.8500, -87.6500)
        }
        for location_name, (lat, lon) in locations.items():
            print(f"\nAcquisition plans for {location_name} ({lat:.4f}, {lon:.4f})") # Avoid truncation
            find_acq_plans_over_location(lat, lon, kml_data_objects)

        # --- Plot all three acquisition plans on a map ---
        # Also mark the target locations on the map
        plt.figure(figsize=(10, 8))
        ax = plt.gca()
        colors = ['red', 'green', 'blue']
        handles = []
        # Plot acquisition-plan layers and build legend handles correctly here
        for idx, (satellite, gdf) in enumerate(kml_data_objects.items()):
            gdf.plot(ax=ax, color=colors[idx % len(colors)], alpha=0.05, edgecolor='k')
            handles.append(mpatches.Patch(color=colors[idx % len(colors)], label=satellite.strip(), alpha=0.05))

        # Draw coastlines using Basemap for better geographic context
        try:
            m = Basemap(projection='cyl',
                        llcrnrlat=-90, urcrnrlat=90,
                        llcrnrlon=-180, urcrnrlon=180,
                        resolution='l',
                        ax=ax)
            # Draw coastlines on the axes; choose zorder so coastlines sit between layers and markers
            m.drawcoastlines(linewidth=0.5, color='black', zorder=2)
            # If Basemap altered axis limits, reset to global extent for consistency
            ax.set_xlim(-180, 180)
            ax.set_ylim(-90, 90)
        except Exception as e:
            # If Basemap is unavailable or fails, log and continue (markers/annotations still plot)
            print(f"Basemap drawing failed: {e}")

        # Predefined offset vectors (in points) to reduce overlapping labels; these will be cycled
        offsets = [(0, 10), (10, 10), (-10, 10), (10, -10), (-10, -10), (0, -12)]
        marker_color = 'white'

        # Plot each target location and annotate with an offset label
        for i, (location_name, (lat, lon)) in enumerate(locations.items()):
            ax.plot(lon, lat, marker='o', color=marker_color, markersize=4)
            offset = offsets[i % len(offsets)]
            ann_kwargs = dict(
                xy=(lon, lat),
                xytext=offset,
                textcoords='offset points',
                fontsize=8,
                ha='center',
                va='center',
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8)
            )
            # Add a subtle line connecting label to point for offsets that are not directly above
            if offset != (0, 10):
                ann_kwargs['arrowprops'] = dict(arrowstyle='-', color='gray', linewidth=0.75, shrinkA=0, shrinkB=0)
            ax.annotate(location_name.split(",")[0], **ann_kwargs)

        ax.set_title('Sentinel-2 Acquisition Plans')
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        plt.tight_layout()
        plt.legend(handles=handles)
        plt.show()
    else:
        print("No KML filenames could be retrieved.")