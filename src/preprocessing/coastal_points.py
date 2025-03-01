"""
Generate evenly spaced reference points along the coastline for coastal counties.
Points are spaced 5km apart using region-specific projections for accurate distances.
Uses region definitions from region_mappings.yaml for proper regional processing.
"""

import geopandas as gpd
from shapely.geometry import Point, LineString
from pathlib import Path
import yaml
import logging
from typing import List, Dict
from tqdm import tqdm
from src.config import (
    CONFIG_DIR,
    PROCESSED_DIR,
    SHORELINE_DIR,
    COASTAL_COUNTIES_FILE,
    REFERENCE_POINTS_FILE
)
import pandas as pd

logger = logging.getLogger(__name__)

# Point spacing in meters (5km)
POINT_SPACING_M = 5000

def load_region_config():
    """Load region configuration from YAML."""
    with open(CONFIG_DIR / "region_mappings.yaml") as f:
        config = yaml.safe_load(f)
    return config['regions']

def get_region_projection(region_name: str, region_def: dict) -> str:
    """Get the appropriate projection for a region.
    
    Args:
        region_name: Name of the region
        region_def: Region definition from config
    
    Returns:
        Projection string for the region
    """
    # Use region-specific projection if defined in config
    if 'projection' in region_def:
        proj = region_def['projection']
        logger.info(f"Using config-defined projection for {region_name}: {proj}")
        return proj
    
    # Default projections for specific regions
    if region_name == 'alaska':
        proj = ("+proj=aea +lat_1=55 +lat_2=65 +lat_0=50 +lon_0=-154 "
                "+x_0=0 +y_0=0 +ellps=GRS80 +datum=NAD83 +units=m +no_defs")
        logger.info(f"Using Alaska-specific projection: {proj}")
        return proj
    elif region_name in ['west_coast', 'pacific_islands']:
        proj = ("+proj=aea +lat_1=34 +lat_2=45.5 +lat_0=40 +lon_0=-120 "
                "+x_0=0 +y_0=0 +ellps=GRS80 +datum=NAD83 +units=m +no_defs")
        logger.info(f"Using West Coast/Pacific projection for {region_name}: {proj}")
        return proj
    
    # Default to continental US Albers Equal Area
    proj = ("+proj=aea +lat_1=20 +lat_2=60 +lat_0=40 +lon_0=-96 "
            "+x_0=0 +y_0=0 +ellps=GRS80 +datum=NAD83 +units=m +no_defs")
    logger.info(f"Using default CONUS projection for {region_name}: {proj}")
    return proj

def create_reference_points(line: LineString, spacing: float = POINT_SPACING_M) -> List[Point]:
    """Create evenly spaced points along a line.
    
    Args:
        line: Input LineString
        spacing: Distance between points in meters
    
    Returns:
        List of Point objects
    """
    # Get line length
    length = line.length
    
    # Calculate number of points (minimum 2)
    num_points = max(2, int(length / spacing))
    
    # Generate points at regular intervals
    points = [
        line.interpolate(i / (num_points - 1), normalized=True)
        for i in range(num_points)
    ]
    
    return points

def process_region(shoreline_gdf: gpd.GeoDataFrame, 
                  counties: gpd.GeoDataFrame, 
                  region_name: str,
                  region_def: dict) -> List[Dict]:
    """Process a single region to generate reference points.
    
    Args:
        shoreline_gdf: GeoDataFrame containing the region's shoreline
        counties: GeoDataFrame containing coastal counties for this region
        region_name: Name of the region
        region_def: Region definition from config
        
    Returns:
        List of dictionaries containing point data
    """
    logger.info(f"\nProcessing region: {region_name}")
    reference_points = []
    
    # Get region-specific projection
    projection = get_region_projection(region_name, region_def)
    
    # Project to appropriate CRS for accurate distances
    shoreline_proj = shoreline_gdf.to_crs(projection)
    counties_proj = counties.to_crs(projection)
    
    # Process each county with progress bar
    for idx, county in tqdm(counties_proj.iterrows(), total=len(counties_proj), 
                          desc=f"Processing {region_name} counties"):
        # Intersect county with coastline
        county_coastline = shoreline_proj.clip(county.geometry)
        
        if len(county_coastline) == 0:
            continue
            
        # Process each coastline segment
        for _, segment in county_coastline.iterrows():
            geom = segment.geometry
            if not geom or geom.is_empty:
                continue
                
            # Handle both LineString and MultiLineString
            lines = [geom] if isinstance(geom, LineString) else list(geom.geoms)
            
            for line in lines:
                # Generate points for this segment
                points = create_reference_points(line)
                
                # Add points with county and region metadata
                for point in points:
                    reference_points.append({
                        'county_fips': county['GEOID'],
                        'county_name': county['NAME'],
                        'state_fips': county['STATEFP'],
                        'region': region_name,
                        'region_display': region_def.get('display_name', region_name.replace('_', ' ').title()),
                        'geometry': point
                    })
    
    return reference_points

def generate_coastal_points() -> gpd.GeoDataFrame:
    """Generate reference points along the coastline for each coastal county.
    Points are spaced 5km apart using region-specific projections.
    
    Returns:
        GeoDataFrame containing reference points with county and region metadata
    """
    # Load region configuration
    regions_config = load_region_config()
    
    # Load coastal counties
    logger.info("Loading coastal counties...")
    counties = gpd.read_parquet(COASTAL_COUNTIES_FILE)
    
    region_gdfs = []
    
    # Process each region from config
    for region_name, region_def in regions_config.items():
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing region: {region_name}")
        logger.info(f"{'='*80}")
        
        region_file = SHORELINE_DIR / f"{region_name}.parquet"
        
        if not region_file.exists():
            logger.warning(f"Shoreline file not found for {region_name}")
            continue
        
        # Load regional shoreline
        logger.info(f"Loading {region_name} shoreline...")
        shoreline = gpd.read_parquet(region_file)
        logger.info(f"Shoreline CRS: {shoreline.crs}")
        
        # Get counties for this region
        region_counties = counties[counties['region'] == region_name]
        
        if len(region_counties) == 0:
            logger.warning(f"No coastal counties found for {region_name}")
            continue
            
        logger.info(f"Found {len(region_counties)} counties in {region_name}")
        
        # Process this region
        region_points = process_region(shoreline, region_counties, region_name, region_def)
        
        # Create GeoDataFrame for this region with correct projection
        region_proj = get_region_projection(region_name, region_def)
        region_gdf = gpd.GeoDataFrame(
            region_points,
            crs=region_proj
        )
        
        # Log coordinate bounds before reprojection
        bounds = region_gdf.total_bounds
        logger.info(f"\nRegion {region_name} bounds in projection {region_proj}:")
        logger.info(f"X min/max: {bounds[0]:.2f}, {bounds[2]:.2f}")
        logger.info(f"Y min/max: {bounds[1]:.2f}, {bounds[3]:.2f}")
        
        # Convert to WGS84 before combining
        region_gdf = region_gdf.to_crs("EPSG:4326")
        
        # Log coordinate bounds after reprojection
        bounds = region_gdf.total_bounds
        logger.info(f"\nRegion {region_name} bounds in WGS84:")
        logger.info(f"Longitude min/max: {bounds[0]:.2f}, {bounds[2]:.2f}")
        logger.info(f"Latitude min/max: {bounds[1]:.2f}, {bounds[3]:.2f}")
        
        region_gdfs.append(region_gdf)
        logger.info(f"Added {len(region_gdf)} points for {region_name}")
    
    # Combine all regions
    points_gdf = pd.concat(region_gdfs, ignore_index=True)
    points_gdf = gpd.GeoDataFrame(points_gdf, crs="EPSG:4326")
    
    logger.info(f"\nGenerated {len(points_gdf)} total reference points")
    logger.info("\nPoints by region:")
    logger.info(points_gdf['region_display'].value_counts())
    
    # Final verification of bounds
    logger.info("\nFinal combined dataset bounds (WGS84):")
    bounds = points_gdf.total_bounds
    logger.info(f"Longitude min/max: {bounds[0]:.2f}, {bounds[2]:.2f}")
    logger.info(f"Latitude min/max: {bounds[1]:.2f}, {bounds[3]:.2f}")
    
    # Save to file
    points_gdf.to_parquet(REFERENCE_POINTS_FILE, compression='snappy', index=False)
    logger.info(f"\nSaved reference points to {REFERENCE_POINTS_FILE}")
    
    return points_gdf

def main():
    """Generate coastal reference points."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        generate_coastal_points()
    except Exception as e:
        logger.error(f"Error generating coastal points: {str(e)}")
        raise

if __name__ == "__main__":
    main() 