# Install apt and pip packages silently
!pip install pycrs &> /dev/null
!pip install boto3 leafmap rasterio localtileserver pycrs &> /dev/null
!apt install gdal-bin &> /dev/null

# Download GeoJSON for Seattle AOI
!curl "https://polygons.openstreetmap.fr/get_geojson.py?id=237385&params=0" -o seattle.geojson &> /dev/null

import os
import ee
import sys
import boto3
import geemap
import requests
import geopandas as gpd
from typing import Union, List

# Authenticate and initialize Earth Engine
ee.Authenticate()
ee.Initialize(project=project)

# Load GeoJSON and convert to shapefile
gdf = gpd.read_file('seattle.geojson')
gdf.to_file('seattle.shp')

# Convert shapefile to EE FeatureCollection
aoi = geemap.shp_to_ee('seattle.shp')

# Filter Sentinel-2 collection: bounds, date, and basic cloud prefilter
sentinel2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
    .filterBounds(aoi) \
    .sort('system:time_start', False) \
    .limit(15)

# Function to compute cloud percentage using SCL band
def calculate_cloud_cover(image):
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
sorted_images = sentinel2.map(calculate_cloud_cover)

# Print cloud % info for each image
image_list = sorted_images.toList(15)
latest_cloudless_product_id = ''

for i in range(15):
    img = ee.Image(image_list.get(i))
    props = img.getInfo()['properties']
    cloud = props.get('cloud_cover_aoi')
    product_id = props.get('PRODUCT_ID')
    if latest_cloudless_product_id == '' and cloud < 0.1:
        latest_cloudless_product_id = product_id

if latest_cloudless_product_id != '':
    print(f"Latest Cloudless Product ID: {latest_cloudless_product_id}")
else:
    print("No cloudless products found.")
    sys.exit(0)

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

s3_path = get_tci_href(latest_cloudless_product_id).replace("s3://eodata/", "")
print(f"s3 path: {s3_path}")

session = boto3.session.Session()
s3 = boto3.resource(
    's3',
    endpoint_url='https://eodata.dataspace.copernicus.eu',
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name='default'
)  # generated secrets

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

download(s3.Bucket("eodata"), s3_path)

!gdalwarp -overwrite -of GTiff -tr 10.0 -10.0 -tap -cutline seattle.geojson -cl seattle -crop_to_cutline -dstalpha -co COMPRESS=NONE -co BIGTIFF=IF_NEEDED $s3_path Seattle.tif

!sha256sum Seattle.tif
