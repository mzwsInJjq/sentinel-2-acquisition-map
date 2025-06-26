"""
Sentinel-2 Cloudless Image Processor for Seattle AOI
Automated pipeline: Earth Engine filtering → S3 download → GDAL processing
Adapted from: https://documentation.dataspace.copernicus.eu/APIs/S3.html#example-script-to-download-product-using-boto3

Required Python packages:
- pycrs
- boto3
- leafmap
- rasterio
- localtileserver
- geemap
- requests
- geopandas
- earthengine-api

System requirements:
- gdal-bin (install with sudo apt-get install gdal-bin)

Standard library modules:
- os
- sys
- subprocess
- typing
"""

import os
import ee
import sys
import boto3
import geemap
import requests
import subprocess
import geopandas as gpd
from typing import Union, List

# Download GeoJSON for Seattle AOI
def download_seattle_geojson():
    url1 = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4/query?objectIds=32408&outSR=32610&f=geojson"
    url2 = 'https://polygons.openstreetmap.fr/get_geojson.py?id=237385&params=0'
    subprocess.run(['curl', '-sSL', url1, '-o' , 'seattle.geojson'], check=True)

# Authenticate and initialize Earth Engine
def authenticate_earth_engine(project):
    ee.Authenticate()
    ee.Initialize(project=project)

# Load GeoJSON and convert to shapefile
def convert_geojson_to_shapefile(geojson_path, shapefile_path):
    gdf = gpd.read_file(geojson_path)
    gdf.to_file(shapefile_path)

# Convert shapefile to EE FeatureCollection
def get_seattle_aoi(shapefile_path):
    aoi = geemap.shp_to_ee(shapefile_path)
    return aoi

# Filter Sentinel-2 collection: bounds, date, and basic cloud prefilter
def filter_sentinel2_collection(aoi):
    sentinel2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
    .filterBounds(aoi) \
    .sort('system:time_start', False) \
    .limit(15)
    return sentinel2

# Function to compute cloud percentage using SCL band
def calculate_cloud_cover(image):
    aoi = get_seattle_aoi("seattle.shp")
    scl = image.select('SCL')

    # Remap SCL classes: 3, 8, 9, 10 → 1 (cloud), all else → 0
    cloud_mask = scl.remap([3, 8, 9, 10], [1, 1, 1, 1], 0).rename('cloud_mask')

    total_pixels = image.select('B2').reduceRegion(
        reducer=ee.Reducer.count(),
        geometry=aoi.geometry(),
        scale=20,
        maxPixels=1e10
    ).get('B2')

    cloud_pixels = cloud_mask.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=aoi.geometry(),
        scale=20,
        maxPixels=1e10
    ).get('cloud_mask')

    cloud_percentage = ee.Number(cloud_pixels).divide(ee.Number(total_pixels)).multiply(100)
    return image.set('cloud_cover_aoi', cloud_percentage)

# Apply cloud percentage computation
def select_latest_cloudless_image(sorted_images):
    image_list = sorted_images.toList(15)
    latest_cloudless_product_id = ''

    for i in range(15):
        img = ee.Image(image_list.get(i))
        props = img.getInfo()['properties']
        cloud = props.get('cloud_cover_aoi')
        product_id = props.get('PRODUCT_ID')
        if latest_cloudless_product_id == '' and cloud < 0.1:
            latest_cloudless_product_id = product_id
            return latest_cloudless_product_id
    return None

def get_tci_href(ids: Union[str, List[str]]) -> Union[str, List[str], None]:
    """
    Get TCI_10m href URLs from Copernicus STAC API.

    Args:
        ids: Single ID string or list of ID strings

    Returns:
        Single href string, list of href strings, or None if failed
    """

    def fetch_href(item_id: str) -> str:
        """Fetch href for single ID."""
        try:
            url = f"https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a/items/{item_id}"
            response = requests.get(url)
            response.raise_for_status()

            data = response.json()
            return data['assets']['TCI_10m']['href']

        except Exception as e:
            print(f"Error fetching {item_id}: {e}")
            return None

    # Handle single ID
    if isinstance(ids, str):
        return fetch_href(ids)

    # Handle list of IDs
    elif isinstance(ids, list):
        return [fetch_href(item_id) for item_id in ids]

    return None

def download(bucket, product: str, target: str = "") -> None:
    """
    Downloads every file in bucket with provided product as prefix

    Raises FileNotFoundError if the product was not found

    Args:
        bucket: boto3 Resource bucket object
        product: Path to product
        target: Local catalog for downloaded files. Should end with an `/`. Default current directory.
    """
    files = bucket.objects.filter(Prefix=product)
    if not list(files):
        raise FileNotFoundError(f"Could not find any files for {product}")
    for file in files:
        os.makedirs(os.path.dirname(file.key), exist_ok=True)
        if not os.path.isdir(file.key):
            bucket.download_file(file.key, f"{target}{file.key}")

def process_gdalwarp(s3_path, output_path):
    process = subprocess.Popen([
        'gdalwarp',
        '-overwrite',
        '-of', 'GTiff',
        '-tr', '10.0', '-10.0',
        '-tap',
        '-cutline', 'seattle.geojson',
        '-cl', 'seattle',
        '-crop_to_cutline',
        '-dstalpha',
        '-co', 'COMPRESS=NONE',
        '-co', 'BIGTIFF=IF_NEEDED',
        s3_path,
        output_path
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Print output as it becomes available
    for line in process.stdout:
        print(line, end='')
    for line in process.stderr:
        print(line, end='')

def main():
    # project = "your_project_id"
    # aws_access_key_id = "your_access_key"
    # aws_secret_access_key = "your_secret_key"

    authenticate_earth_engine(project)
    download_seattle_geojson()
    convert_geojson_to_shapefile("seattle.geojson", "seattle.shp")
    aoi = get_seattle_aoi("seattle.shp")
    sentinel2 = filter_sentinel2_collection(aoi)
    sorted_images = sentinel2.map(calculate_cloud_cover)
    latest_cloudless_product_id = select_latest_cloudless_image(sorted_images)
    if not latest_cloudless_product_id:
        print("No cloudless products found.")
        sys.exit(0)

    s3_path = get_tci_href(latest_cloudless_product_id).replace("s3://eodata/", "")
    print(f"s3 path: {s3_path}")

    session = boto3.session.Session()
    s3 = boto3.resource(
        's3',
        endpoint_url='https://eodata.dataspace.copernicus.eu',
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name='default'
    )

    download(s3.Bucket("eodata"), s3_path)
    process_gdalwarp(s3_path, "Seattle.tif")
    result = subprocess.run(['sha256sum', 'Seattle.tif'], capture_output=True, text=True, check=True)
    print(result.stdout)

if __name__ == '__main__':
    main()
