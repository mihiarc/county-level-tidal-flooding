"""
Main module for water level imputation at coastal reference points.
Orchestrates the process of:

1. Loading preprocessed spatial relationships from module `spatial_ops.py`
2. Uses module `weight_calculator.py` to calculate weights and adjustments
3. Preparing data structures for the next phase saving to file location `data/processed/imputation/imputation_structure.parquet`

The imputation output is designed to support:
- Mapping of historic water levels to coastal county reference points
- Projection of future water levels to coastal county reference points
- Temporal interpolation between gauge readings
- Handling of missing or incomplete gauge data
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
import logging
from datetime import datetime
import yaml
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm

from src.config import (
    CONFIG_DIR,
    PROCESSED_DIR,
    IMPUTATION_DIR,
    IMPUTATION_LOGS_DIR,
    COASTAL_COUNTIES_FILE,
    REFERENCE_POINTS_FILE,
    OUTPUT_DIR,
    TIDE_STATIONS_DIR,
    REGION_CONFIG
)

from .data_loader import DataLoader
from .spatial_ops import NearestGaugeFinder
from .weight_calculator import WeightCalculator

logger = logging.getLogger(__name__)

def process_region(region: str,
                  region_info: dict,
                  reference_points: gpd.GeoDataFrame,
                  gauge_stations: gpd.GeoDataFrame) -> Optional[pd.DataFrame]:
    """
    Process a single region.
    
    Args:
        region: Region identifier
        region_info: Region configuration dictionary
        reference_points: Reference points GeoDataFrame
        gauge_stations: Gauge stations GeoDataFrame
        
    Returns:
        DataFrame containing imputation structure for the region or None if error
    """
    try:
        logger.info(f"\nProcessing region: {region}")
        logger.info(f"States included: {', '.join(region_info['state_codes'])}")
        
        # Initialize components for this region
        gauge_finder = NearestGaugeFinder(region_config=REGION_CONFIG)
        weight_calculator = WeightCalculator(
            max_distance_meters=100000,  # 100km max distance
            power=2,  # inverse distance power
            min_weight=0.1
        )
        
        # Find nearest gauges for reference points in this region
        mappings = gauge_finder.find_nearest(
            reference_points=reference_points,
            gauge_stations=gauge_stations,
            region=region
        )
        
        if not mappings:
            logger.warning(f"No mappings found for region {region}")
            return None
            
        # Calculate weights for gauge stations
        weighted_mappings = weight_calculator.calculate_weights(mappings)
        
        # Convert to DataFrame
        records = []
        for mapping in weighted_mappings:
            for gauge in mapping['mappings']:
                records.append({
                    'reference_point_id': mapping['reference_point_id'],
                    'county_fips': mapping['county_fips'],
                    'region': region,
                    'region_name': region_info['name'],
                    'station_id': gauge['station_id'],
                    'station_name': gauge['station_name'],
                    'sub_region': gauge['sub_region'],
                    'distance_meters': gauge['distance_meters'],
                    'weight': gauge['weight']
                })
                
        df = pd.DataFrame.from_records(records)
        
        # Log statistics with improved clarity
        if not df.empty:
            total_counties = df['county_fips'].nunique()
            total_stations = df['station_id'].nunique()
            total_mappings = len(df)
            
            logger.info(f"\nRegion Summary for {region}:")
            logger.info(f"Total unique counties: {total_counties}")
            logger.info(f"Total tide stations: {total_stations}")
            logger.info(f"Total point-to-station mappings: {total_mappings}")
            logger.info("\nNote: Each county is considered for all subregions, with weights determined by distance")
            
            # Log sub-region statistics with improved clarity
            logger.info("\nSubregion Details:")
            for sub_region in sorted(df['sub_region'].unique()):
                if sub_region:
                    sub_df = df[df['sub_region'] == sub_region]
                    sub_counties = sub_df['county_fips'].nunique()
                    sub_stations = sub_df['station_id'].nunique()
                    avg_distance = sub_df['distance_meters'].mean()
                    avg_weight = sub_df['weight'].mean()
                    
                    logger.info(f"\nSubregion: {sub_region}")
                    logger.info(f"  Available stations: {sub_stations}")
                    logger.info(f"  Counties with mappings: {sub_counties} (all counties in region)")
                    logger.info(f"  Average distance to stations: {avg_distance:,.2f} meters")
                    logger.info(f"  Average station weight: {avg_weight:.4f}")
                    logger.info("  Note: Weights decrease with distance, stations beyond 100km have minimal influence")
            
        return df
        
    except Exception as e:
        logger.error(f"Error processing region {region}: {str(e)}")
        return None

class ImputationManager:
    """Manages the imputation of water levels at reference points."""
    
    def __init__(self,
                 reference_points_file: Path = REFERENCE_POINTS_FILE,
                 gauge_stations_file: Path = TIDE_STATIONS_DIR,
                 output_dir: Path = OUTPUT_DIR / "imputation",
                 region_config: Path = REGION_CONFIG,
                 n_processes: int = None):
        """Initialize imputation manager."""
        self.reference_points_file = reference_points_file
        self.gauge_stations_file = gauge_stations_file
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.n_processes = n_processes or max(1, mp.cpu_count() - 2)
        
        # Load region configuration
        with open(region_config) as f:
            config = yaml.safe_load(f)
            self.region_config = config['regions']
            self.metadata = config.get('metadata', {})
            
        # Initialize data loader
        self.data_loader = DataLoader()
        
        self._setup_logging()
        
        logger.info(f"Initialized ImputationManager with {len(self.region_config)} regions")
        logger.info(f"Using {self.n_processes} processes for regional processing")
        logger.info(f"Data source: {self.metadata.get('source', 'Unknown')}")
        logger.info(f"Last updated: {self.metadata.get('last_updated', 'Unknown')}")
    
    def _setup_logging(self):
        """Configure logging for imputation process."""
        log_dir = self.output_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"imputation_{timestamp}.log"
        
        # Configure root logger
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),  # Console handler
                logging.FileHandler(log_file)  # File handler
            ]
        )
        
        logger.info("Logging configured for both console and file output")

    def save_imputation_structure(self,
                                df: pd.DataFrame,
                                region: str) -> Path:
        """
        Save imputation structure for a region.
        
        Args:
            df: DataFrame containing imputation structure
            region: Region identifier
            
        Returns:
            Path to saved file
        """
        if df is None or df.empty:
            logger.warning(f"No data to save for region {region}")
            return None
            
        # Create output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"imputation_structure_{region}_{timestamp}.parquet"
        output_path = self.output_dir / filename
        
        # Save to parquet
        df.to_parquet(output_path)
        logger.info(f"Saved imputation structure for region {region} to {output_path}")
        
        return output_path

    def run(self) -> Dict[str, Path]:
        """
        Run imputation structure preparation for all regions in parallel.
        
        Returns:
            Dictionary mapping region names to output file paths
        """
        output_files = {}
        
        # Load data once for all regions
        reference_points = self.data_loader.load_reference_points()
        gauge_stations = self.data_loader.load_gauge_stations()
        
        if reference_points.empty or gauge_stations.empty:
            logger.error("Failed to load required data")
            return output_files
        
        # Process regions in parallel
        with ProcessPoolExecutor(max_workers=self.n_processes) as executor:
            # Submit all regions
            future_to_region = {
                executor.submit(
                    process_region,
                    region,
                    self.region_config[region],
                    reference_points,
                    gauge_stations
                ): region 
                for region in self.region_config
            }
            
            # Process results as they complete
            for future in tqdm(as_completed(future_to_region), 
                             total=len(self.region_config),
                             desc="Processing regions"):
                region = future_to_region[future]
                try:
                    df = future.result()
                    if df is not None:
                        output_path = self.save_imputation_structure(df, region)
                        if output_path:
                            output_files[region] = output_path
                except Exception as e:
                    logger.error(f"Error processing region {region}: {str(e)}")
        
        return output_files

if __name__ == "__main__":
    # Run imputation process
    manager = ImputationManager()
    output_files = manager.run()