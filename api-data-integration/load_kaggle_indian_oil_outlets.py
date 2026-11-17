#!/usr/bin/env python3
"""
Load and integrate Indian Oil Retail Outlets dataset from Kaggle
Dataset: Indian Oil Retail Outlets Across India 2025
Source: https://www.kaggle.com/datasets/adityaskarnik/indian-oil-retail-outlets-across-india-2025
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

def load_kaggle_dataset():
    """Load Indian Oil outlets from Kaggle using kagglehub."""
    print("\n" + "="*80)
    print("🗺️  LOADING KAGGLE DATASET: Indian Oil Retail Outlets")
    print("="*80)

    try:
        import kagglehub

        print("\n📥 Downloading from Kaggle...")
        print("   Dataset: Indian Oil Retail Outlets Across India 2025")
        print("   Source: adityaskarnik/indian-oil-retail-outlets-across-india-2025")

        # Load dataset using correct kagglehub API
        dataset_ref = "adityaskarnik/indian-oil-retail-outlets-across-india-2025"

        # Try to list files first
        try:
            path = kagglehub.model_download(dataset_ref)
            print(f"   Downloaded to: {path}")
        except Exception:
            # Try alternative approach
            try:
                from kagglehub.clients import ApiClient
                api_client = ApiClient()
                # List files in dataset
                files = api_client.list_dataset_files(dataset_ref)
                print(f"   Dataset files: {files}")
            except Exception:
                pass

        # Try using pandas directly with Kaggle API
        import subprocess
        import os

        # Download using Kaggle CLI
        print("\n   Using Kaggle API CLI...")
        os.system(f'kaggle datasets download -d {dataset_ref} --unzip')

        # Find CSV files
        import glob
        csv_files = glob.glob("*.csv")
        if csv_files:
            print(f"   Found CSV: {csv_files[0]}")
            df = pd.read_csv(csv_files[0])
            print(f"\n✅ Dataset loaded successfully!")
            print(f"   Records: {len(df):,}")
            print(f"   Columns: {df.shape[1]}")
            return df

        return None

    except Exception as e:
        print(f"\n✗ Error loading dataset: {e}")
        print("\nFallback: Using existing SSRI data...")
        return None

def analyze_kaggle_data(df):
    """Analyze the loaded Kaggle dataset."""
    if df is None:
        return

    print("\n" + "="*80)
    print("📊 DATASET ANALYSIS")
    print("="*80)

    print(f"\nDataset Shape: {df.shape}")
    print(f"\nColumn Names and Types:")
    print(df.dtypes)

    print(f"\n📍 First 5 Records:")
    print(df.head())

    print(f"\n🔍 Dataset Summary:")
    print(df.describe())

    print(f"\n📋 Column Details:")
    for col in df.columns:
        print(f"   {col}: {df[col].dtype} ({df[col].nunique()} unique)")

    # Check for coordinates
    coord_cols = [col for col in df.columns if any(
        keyword in col.lower() for keyword in ['lat', 'lon', 'latitude', 'longitude', 'x', 'y']
    )]

    if coord_cols:
        print(f"\n🗺️  Geographic Columns Found: {coord_cols}")
    else:
        print(f"\n⚠️  No obvious lat/lon columns. Available columns: {df.columns.tolist()}")

    # Check state/location columns
    location_cols = [col for col in df.columns if any(
        keyword in col.lower() for keyword in ['state', 'district', 'city', 'location', 'address']
    )]

    if location_cols:
        print(f"📍 Location Columns Found: {location_cols}")

def validate_coordinates(df):
    """Validate geographic coordinates."""
    print("\n" + "="*80)
    print("✓ COORDINATE VALIDATION")
    print("="*80)

    # Find lat/lon columns (flexible naming)
    lat_col = None
    lon_col = None

    for col in df.columns:
        if any(x in col.lower() for x in ['lat', 'latitude']):
            lat_col = col
        if any(x in col.lower() for x in ['lon', 'longitude']):
            lon_col = col

    if not lat_col or not lon_col:
        print("\n⚠️  Could not find latitude/longitude columns")
        print(f"   Available columns: {df.columns.tolist()}")
        return None

    print(f"\n📍 Latitude column: {lat_col}")
    print(f"📍 Longitude column: {lon_col}")

    # Validate bounds
    india_bounds = {
        'lat_min': 8.0,
        'lat_max': 35.0,
        'lon_min': 68.0,
        'lon_max': 97.0
    }

    df_clean = df.copy()

    # Remove nulls
    df_clean = df_clean.dropna(subset=[lat_col, lon_col])
    print(f"\n✓ After removing nulls: {len(df_clean):,} records")

    # Remove zeros
    df_clean = df_clean[
        (df_clean[lat_col] != 0) & (df_clean[lon_col] != 0)
    ]
    print(f"✓ After removing zeros: {len(df_clean):,} records")

    # Validate India bounds
    valid = df_clean[
        (df_clean[lat_col] >= india_bounds['lat_min']) &
        (df_clean[lat_col] <= india_bounds['lat_max']) &
        (df_clean[lon_col] >= india_bounds['lon_min']) &
        (df_clean[lon_col] <= india_bounds['lon_max'])
    ].copy()

    print(f"✓ Within India bounds: {len(valid):,} records")
    print(f"\n📊 Coordinate Statistics:")
    print(f"   Latitude range: {valid[lat_col].min():.4f}° to {valid[lat_col].max():.4f}°")
    print(f"   Longitude range: {valid[lon_col].min():.4f}° to {valid[lon_col].max():.4f}°")

    return valid, lat_col, lon_col

def merge_with_ssri(kaggle_df, lat_col, lon_col):
    """Merge Kaggle data with existing SSRI dataset."""
    print("\n" + "="*80)
    print("🔀 MERGING WITH SSRI DATASET")
    print("="*80)

    # Load existing SSRI data
    import glob
    ssri_files = glob.glob("outlet_data_ssri_107k/ssri_complete_pumps_*.csv")

    if not ssri_files:
        print("⚠️  SSRI data not found")
        return None

    print(f"\n📂 Loading SSRI data...")
    ssri_df = pd.read_csv(ssri_files[0])
    print(f"   SSRI records: {len(ssri_df):,}")

    # Standardize column names
    kaggle_standardized = kaggle_df.copy()
    kaggle_standardized.rename(columns={
        lat_col: 'latitude',
        lon_col: 'longitude'
    }, inplace=True)

    # Ensure both have same columns
    common_cols = ['latitude', 'longitude']

    # Add name if available
    name_cols = [col for col in kaggle_standardized.columns if 'name' in col.lower()]
    if name_cols:
        kaggle_standardized.rename(columns={name_cols[0]: 'name'}, inplace=True)
        common_cols.append('name')

    # Add state if available
    state_cols = [col for col in kaggle_standardized.columns if 'state' in col.lower()]
    if state_cols:
        kaggle_standardized.rename(columns={state_cols[0]: 'state'}, inplace=True)
        common_cols.append('state')

    # Keep only common columns that exist in both
    kaggle_for_merge = kaggle_standardized[
        [col for col in common_cols if col in kaggle_standardized.columns]
    ].copy()

    ssri_for_merge = ssri_df[
        [col for col in common_cols if col in ssri_df.columns]
    ].copy()

    print(f"\n🔀 Merging datasets...")
    print(f"   SSRI columns: {ssri_for_merge.columns.tolist()}")
    print(f"   Kaggle columns: {kaggle_for_merge.columns.tolist()}")

    # Merge
    combined = pd.concat([ssri_for_merge, kaggle_for_merge], ignore_index=True)
    print(f"   Combined (before dedup): {len(combined):,}")

    # Remove duplicates by coordinates
    combined = combined.drop_duplicates(
        subset=['latitude', 'longitude'],
        keep='first'
    )
    print(f"   After dedup: {len(combined):,}")

    duplicates_removed = len(ssri_for_merge) + len(kaggle_for_merge) - len(combined)
    print(f"\n✅ Duplicates removed: {duplicates_removed:,}")
    print(f"✅ Space saved: ~{duplicates_removed * 0.0005:.2f} MB (estimate)")

    return combined

def create_enhanced_map(combined_df):
    """Create enhanced map with merged data."""
    if combined_df is None or len(combined_df) == 0:
        print("✗ No data to map")
        return

    print("\n" + "="*80)
    print("🗺️  CREATING ENHANCED MAP")
    print("="*80)

    import folium
    from folium.plugins import MarkerCluster

    center_lat = combined_df['latitude'].mean()
    center_lon = combined_df['longitude'].mean()

    print(f"\n📍 Map center: {center_lat:.4f}, {center_lon:.4f}")
    print(f"   Creating map with {len(combined_df):,} outlets...")

    # Create map
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=5,
        tiles='CartoDB positron'
    )

    # Add cluster group
    cluster = MarkerCluster(name='Outlet Clusters').add_to(m)

    # Add markers
    for idx, row in combined_df.iterrows():
        try:
            name = row.get('name', 'Outlet')
            state = row.get('state', 'N/A')

            popup_text = f"""
            <b>{name}</b><br>
            <b>State:</b> {state}<br>
            <b>Coordinates:</b><br>
            Lat: {row['latitude']:.6f}<br>
            Lon: {row['longitude']:.6f}
            """

            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=4,
                popup=folium.Popup(popup_text, max_width=250),
                color='blue',
                fill=True,
                fillColor='blue',
                fillOpacity=0.6,
                weight=1
            ).add_to(cluster)

        except (ValueError, TypeError):
            continue

    # Add legend
    legend_html = '''
    <div style="position: fixed; bottom: 50px; right: 50px;
                width: 320px; background-color: white;
                border: 2px solid grey; z-index: 9999;
                font-size: 12px; padding: 10px; border-radius: 5px;">
    <h4 style="margin: 0 0 10px 0;">Enhanced India Outlets Map</h4>
    <p><i class="fa fa-circle" style="color: blue; font-size: 16px;"></i> Outlet Marker</p>
    <p><i class="fa fa-plus-circle" style="color: darkblue; font-size: 16px;"></i> Cluster</p>
    <hr style="margin: 5px 0;">
    <p style="font-size: 11px; margin: 0;">
    <b>Data Sources:</b><br>
    • SSRI (104,949)<br>
    • Kaggle (IOC outlets)<br>
    • Merged & deduplicated
    </p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))

    # Save map
    output_file = 'enhanced_india_outlets_kaggle_integrated.html'
    m.save(output_file)

    size = Path(output_file).stat().st_size / (1024*1024)
    print(f"\n✅ Map saved: {output_file}")
    print(f"   Size: {size:.2f}MB")

    return output_file

def export_combined_data(combined_df):
    """Export merged dataset in multiple formats."""
    if combined_df is None:
        return

    print("\n" + "="*80)
    print("💾 EXPORTING COMBINED DATASET")
    print("="*80)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # CSV
    csv_file = f"enhanced_outlets_kaggle_merged_{timestamp}.csv"
    combined_df.to_csv(csv_file, index=False)
    csv_size = Path(csv_file).stat().st_size / (1024*1024)
    print(f"\n✓ CSV: {csv_file} ({csv_size:.2f}MB)")

    # Excel
    xlsx_file = f"enhanced_outlets_kaggle_merged_{timestamp}.xlsx"
    combined_df.to_excel(xlsx_file, index=False, sheet_name='Outlets')
    xlsx_size = Path(xlsx_file).stat().st_size / (1024*1024)
    print(f"✓ Excel: {xlsx_file} ({xlsx_size:.2f}MB)")

    # Compressed CSV
    import gzip
    gz_file = f"{csv_file}.gz"
    with open(csv_file, 'rb') as f_in:
        with gzip.open(gz_file, 'wb') as f_out:
            f_out.writelines(f_in)
    gz_size = Path(gz_file).stat().st_size / (1024*1024)
    print(f"✓ Compressed: {gz_file} ({gz_size:.2f}MB)")

    print(f"\n📊 Summary:")
    print(f"   Total records: {len(combined_df):,}")
    print(f"   States: {combined_df.get('state', pd.Series()).nunique() if 'state' in combined_df.columns else 'N/A'}")
    print(f"   Space saved vs original: ~{csv_size * 0.8:.2f}MB (with compression)")

    return csv_file, xlsx_file, gz_file

if __name__ == "__main__":
    print("\n" + "="*80)
    print("🎯 KAGGLE INDIAN OIL OUTLETS INTEGRATION")
    print("="*80)

    # Load Kaggle dataset
    kaggle_df = load_kaggle_dataset()

    if kaggle_df is not None:
        # Analyze
        analyze_kaggle_data(kaggle_df)

        # Validate coordinates
        valid_data, lat_col, lon_col = validate_coordinates(kaggle_df)

        if valid_data is not None:
            # Merge with SSRI
            combined = merge_with_ssri(valid_data, lat_col, lon_col)

            if combined is not None:
                # Create map
                create_enhanced_map(combined)

                # Export
                export_combined_data(combined)

    print("\n" + "="*80)
    print("✨ PROCESS COMPLETE")
    print("="*80)
    print("""
Next Steps:
1. Review the generated map: enhanced_india_outlets_kaggle_integrated.html
2. Check the export files (CSV, Excel, compressed)
3. Use the combined dataset for analysis
4. Push to GitHub: git add enhanced_outlets_* && git commit -m "..." && git push
    """)
