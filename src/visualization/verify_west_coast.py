"""
Script to verify West Coast shoreline data with counties and tide stations.
"""

import geopandas as gpd
from pathlib import Path
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
import yaml

def plot_west_coast_shoreline(shapefile_path: Path, county_path: Path, stations_path: Path, output_path: Path):
    """Create a focused map of West Coast shoreline data from shapefile.
    
    Args:
        shapefile_path: Path to shoreline shapefile
        county_path: Path to county shapefile
        stations_path: Path to tide stations config
        output_path: Path to save the map
    """
    # Read the shapefile and filter for West Coast states
    print("Reading shoreline shapefile...")
    shoreline = gpd.read_file(shapefile_path)
    west_states = ['CA', 'OR', 'WA']  # West Coast states
    west_shoreline = shoreline[shoreline['FIPS_ALPHA'].isin(west_states)].copy()
    print(f"Total West Coast features: {len(west_shoreline)}")
    
    # Read and filter county shapefile for West Coast states
    print("Reading county shapefile...")
    counties = gpd.read_file(county_path)
    state_fips = ['06', '41', '53']  # FIPS codes for CA, OR, WA
    west_counties = counties[counties['STATEFP'].isin(state_fips)].copy()
    print(f"West Coast counties: {len(west_counties)}")
    
    # Read tide stations configuration
    print("Reading tide stations configuration...")
    with open(stations_path) as f:
        stations_config = yaml.safe_load(f)
    
    # Get the actual bounds of the data
    bounds = west_shoreline.total_bounds
    print(f"Data bounds: {bounds}")
    
    # Set up West Coast-specific projection
    projection = ccrs.AlbersEqualArea(
        central_longitude=-122.0,  # Centered on West Coast
        central_latitude=40.0,
        standard_parallels=(36.0, 44.0)
    )
    
    # Create figure and axis
    fig, ax = plt.subplots(
        figsize=(8, 15),  # Tall figure for north-south coastline
        subplot_kw={'projection': projection}
    )
    
    # Add context features
    ax.add_feature(cfeature.LAND.with_scale('10m'), facecolor='#E6E6E6', alpha=0.3)
    ax.add_feature(cfeature.OCEAN.with_scale('10m'), facecolor='#FFFFFF', alpha=0.3)
    ax.add_feature(cfeature.COASTLINE.with_scale('10m'), edgecolor='gray', linewidth=0.5)
    
    # Project and plot the data
    west_shoreline = west_shoreline.to_crs(projection.proj4_init)
    west_counties = west_counties.to_crs(projection.proj4_init)
    
    # Plot county boundaries
    west_counties.boundary.plot(
        ax=ax,
        color='#404040',
        linewidth=1.5,
        linestyle='--',
        alpha=0.7
    )
    
    # Plot shoreline features
    west_shoreline.plot(
        ax=ax,
        color='#FF3366',
        linewidth=2.0,
        alpha=1.0
    )
    
    # Add tide gauge stations
    for station_id, station in stations_config['stations'].items():
        lon = station['location']['lon']
        lat = station['location']['lat']
        
        # Plot marker
        ax.plot(lon, lat, 
                marker='o',
                color='#0066CC',
                markersize=8,
                transform=ccrs.PlateCarree(),
                zorder=5)
        
        # Add label with station name
        ax.text(lon + 0.05, lat,
                station['name'],
                color='#0066CC',
                fontsize=8,
                transform=ccrs.PlateCarree(),
                ha='left',
                va='center')
    
    # Set map extent to show all of West Coast region
    ax.set_extent([-125.0, -116.0, 32.5, 49.0], crs=ccrs.PlateCarree())
    
    # Add gridlines
    gl = ax.gridlines(
        draw_labels=True,
        x_inline=False,
        y_inline=False,
        linewidth=0.5,
        color='gray',
        alpha=0.3
    )
    gl.top_labels = False
    gl.right_labels = False
    
    # Add title
    plt.title('West Coast Shoreline Coverage Analysis', pad=10)
    
    # Save the map
    plt.savefig(output_path, dpi=300, bbox_inches='tight', pad_inches=0.1)
    plt.close()
    
    print(f"\nSaved map to {output_path}")

def main():
    shapefile_path = Path('data/raw/shapefile_shoreline/Western/Western.shp')
    county_path = Path('data/raw/shapefile_county/tl_2024_us_county.shp')
    stations_path = Path('config/west_coast_tide_stations.yaml')
    output_path = Path('output/maps/verification/west_coast_counties_verification.png')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    plot_west_coast_shoreline(shapefile_path, county_path, stations_path, output_path)

if __name__ == '__main__':
    main() 