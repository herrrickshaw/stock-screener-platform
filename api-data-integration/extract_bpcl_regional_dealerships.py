#!/usr/bin/env python3
"""
BPCL COMPLETE REGIONAL DEALERSHIP EXTRACTION
============================================
Extracts ALL BPCL dealerships across India using regional filters:
- NORTH: Chandigarh, Delhi, Haryana, Himachal Pradesh, Jammu & Kashmir, Punjab, Uttarakhand, Uttar Pradesh
- SOUTH: Andhra Pradesh, Karnataka, Kerala, Tamil Nadu, Telangana
- EAST: Assam, Bihar, Jharkhand, Odisha, West Bengal
- WEST: Gujarat, Goa, Maharashtra, Rajasthan

Source: https://www.bharatpetroleum.in/bharat-petroleum-for/business-associates/dealership-data
Method: Regional filter extraction via POST requests
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
from datetime import datetime
from pathlib import Path
import re
import time

class BPCLRegionalExtractor:
    """
    Extracts BPCL dealership data using regional filters.

    Uses ASP.NET form submission to filter by region and extract all dealerships.
    """

    def __init__(self):
        """Initialize regional extractor."""
        self.base_url = "https://www.bharatpetroleum.in"
        self.dealership_url = "/bharat-petroleum-for/business-associates/dealership-data"
        self.session = requests.Session()
        self.all_dealerships = {}  # Use dict for deduplication by key
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Regional groupings for filtering
        self.regions = {
            'NORTH': ['North'],
            'SOUTH': ['South'],
            'EAST': ['East'],
            'WEST': ['West'],
            'CENTRAL': ['Central'],
            'NORTHEAST': ['North East']
        }

        self.region_stats = {}

    def fetch_page_with_filter(self, region: str):
        """
        Fetch dealership data filtered by region.

        Args:
            region (str): Region filter value (North, South, East, West, Central, North East)

        Returns:
            str: HTML content of filtered page
        """
        print(f"  🌐 Fetching {region} region dealerships...", end=" ", flush=True)

        try:
            # Set headers to mimic browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': f'{self.base_url}{self.dealership_url}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            # First, get the page to extract ViewState
            print("(loading)...", end=" ", flush=True)
            response = self.session.get(
                f'{self.base_url}{self.dealership_url}',
                headers=headers,
                timeout=30
            )

            if response.status_code != 200:
                print(f"✗ Status {response.status_code}")
                return None

            # Parse ViewState and other ASP.NET fields
            soup = BeautifulSoup(response.text, 'html.parser')
            viewstate = soup.find('input', {'id': '__VIEWSTATE'})
            viewstate_gen = soup.find('input', {'id': '__VIEWSTATEGENERATOR'})
            event_validation = soup.find('input', {'id': '__EVENTVALIDATION'})

            viewstate_val = viewstate.get('value', '') if viewstate else ''
            viewstate_gen_val = viewstate_gen.get('value', '') if viewstate_gen else ''
            event_val = event_validation.get('value', '') if event_validation else ''

            # Prepare POST data with region filter
            post_data = {
                '__VIEWSTATE': viewstate_val,
                '__VIEWSTATEGENERATOR': viewstate_gen_val,
                '__EVENTVALIDATION': event_val,
                'ddlRegion': region,  # Key filter parameter
                'gvDealerData_PageIndex': '0'
            }

            # Submit form with region filter
            print("(filtering)...", end=" ", flush=True)
            response = self.session.post(
                f'{self.base_url}{self.dealership_url}',
                data=post_data,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                print(f"✓")
                return response.text
            else:
                print(f"✗ Status {response.status_code}")
                return None

        except Exception as e:
            print(f"✗ Error: {str(e)[:40]}")
            return None

    def parse_dealerships_from_html(self, html_content: str, region: str) -> list:
        """
        Parse dealership records from HTML table.

        Args:
            html_content (str): HTML page content
            region (str): Region being parsed (for tracking)

        Returns:
            list: List of dealership dictionaries
        """
        dealerships = []

        if not html_content:
            return dealerships

        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            table = soup.find('table', {'id': 'gvDealerData'})

            if not table:
                return dealerships

            rows = table.find_all('tr')

            for row_idx, row in enumerate(rows):
                cells = row.find_all('td')

                if len(cells) >= 5:
                    try:
                        name = self._extract_text(cells[0])
                        address = self._extract_text(cells[1])
                        city = self._extract_text(cells[2])
                        postal_code = self._extract_text(cells[3])
                        customer_code = self._extract_text(cells[4])

                        if name:
                            dealership = {
                                'name': name,
                                'address': address,
                                'city': city,
                                'postal_code': postal_code,
                                'customer_code': customer_code,
                                'region': region,
                                'company': 'BPCL',
                                'source': 'BPCL Official Website',
                                'extraction_date': datetime.now().strftime('%Y-%m-%d')
                            }
                            dealerships.append(dealership)
                    except Exception:
                        continue

            return dealerships

        except Exception as e:
            print(f"    Error parsing HTML: {str(e)[:50]}")
            return dealerships

    def _extract_text(self, cell) -> str:
        """Extract clean text from table cell."""
        try:
            span = cell.find('span')
            text = span.get_text(strip=True) if span else cell.get_text(strip=True)
            return ' '.join(text.split()) if text else ''
        except (AttributeError, TypeError):
            return ''

    def deduplicate_dealership(self, dealership: dict) -> bool:
        """
        Add dealership with deduplication by name + city + postal code.

        Returns:
            bool: True if new record added, False if duplicate
        """
        # Create unique key from dealership details
        key = f"{dealership['name'].upper()}_{dealership['city'].upper()}_{dealership['postal_code']}"

        if key not in self.all_dealerships:
            self.all_dealerships[key] = dealership
            return True
        else:
            # If already exists, update with region if missing
            if dealership['region'] and not self.all_dealerships[key].get('region'):
                self.all_dealerships[key]['region'] = dealership['region']
            return False

    def extract_all_regions(self):
        """Extract dealerships from all regions."""
        print("\n" + "="*80)
        print("🔍 EXTRACTING BPCL DEALERSHIPS BY REGION")
        print("="*80)

        regions_to_extract = ['North', 'South', 'East', 'West', 'Central', 'North East']

        for region in regions_to_extract:
            print(f"\n📍 Region: {region}")

            # Fetch filtered page
            html_content = self.fetch_page_with_filter(region)

            if not html_content:
                self.region_stats[region] = {'fetched': 0, 'added': 0}
                continue

            # Parse dealerships
            dealerships = self.parse_dealerships_from_html(html_content, region)
            print(f"    Found: {len(dealerships)} dealerships")

            # Add with deduplication
            added = 0
            for dealership in dealerships:
                if self.deduplicate_dealership(dealership):
                    added += 1

            print(f"    Added: {added} new dealerships")
            self.region_stats[region] = {
                'fetched': len(dealerships),
                'added': added
            }

            # Rate limiting
            time.sleep(1)

        print(f"\n✅ Regional extraction complete")
        print(f"   Total unique dealerships: {len(self.all_dealerships)}")

    def enrich_dealership_data(self):
        """Enrich dealership data with additional fields."""
        print("\n🔍 Enriching dealership data...")

        # State mapping by postal code prefix
        state_map = {
            '16': 'Chandigarh', '17': 'Himachal Pradesh', '18': 'Haryana',
            '19': 'Punjab', '20': 'Delhi', '21': 'Uttar Pradesh', '22': 'Uttar Pradesh',
            '23': 'Rajasthan', '24': 'Gujarat', '25': 'Gujarat', '26': 'Madhya Pradesh',
            '27': 'Madhya Pradesh', '28': 'Maharashtra', '29': 'Maharashtra',
            '30': 'Andhra Pradesh', '31': 'Karnataka', '32': 'Tamil Nadu',
            '33': 'Kerala', '34': 'West Bengal', '35': 'Odisha', '36': 'Jharkhand',
            '37': 'Chhattisgarh', '38': 'Assam', '39': 'Meghalaya', '40': 'Manipur',
            '41': 'Mizoram', '42': 'Nagaland', '43': 'Tripura', '50': 'Bihar',
            '80': 'Goa', '90': 'Jammu & Kashmir', '94': 'Ladakh', '95': 'Puducherry'
        }

        for dealership in self.all_dealerships.values():
            # Extract state from postal code
            postal = dealership.get('postal_code', '')[:2]
            dealership['state'] = state_map.get(postal, 'Unknown')

            # Add standard fields
            dealership['latitude'] = None
            dealership['longitude'] = None
            dealership['dealer_type'] = 'Petrol Pump'
            dealership['status'] = 'Active'
            dealership['phone'] = ''

        print(f"  ✓ Data enrichment complete")

    def export_complete_database(self, output_dir: str = "./outlet_data_bpcl_complete"):
        """Export complete BPCL dealership database."""
        print("\n" + "="*80)
        print("💾 EXPORTING COMPLETE BPCL DEALERSHIP DATABASE")
        print("="*80)

        Path(output_dir).mkdir(exist_ok=True)

        if not self.all_dealerships:
            print("✗ No data to export")
            return

        # Create DataFrame
        df = pd.DataFrame(list(self.all_dealerships.values()))

        # Export CSV
        print(f"\n  Exporting CSV...")
        csv_path = f"{output_dir}/bpcl_complete_dealerships_{self.timestamp}.csv"
        df.to_csv(csv_path, index=False)
        csv_size = Path(csv_path).stat().st_size / (1024*1024)
        print(f"    ✓ {csv_path} ({csv_size:.2f}MB, {len(df)} records)")

        # Export JSON
        print(f"  Exporting JSON...")
        json_path = f"{output_dir}/bpcl_complete_dealerships_{self.timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump(list(self.all_dealerships.values()), f, indent=2)
        json_size = Path(json_path).stat().st_size / (1024*1024)
        print(f"    ✓ {json_path} ({json_size:.2f}MB)")

        # Export GeoJSON (coordinates null for now)
        print(f"  Exporting GeoJSON...")
        geojson = {"type": "FeatureCollection", "features": []}
        for dealer in self.all_dealerships.values():
            if dealer.get('latitude') and dealer.get('longitude'):
                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [dealer['longitude'], dealer['latitude']]
                    },
                    "properties": {
                        "name": dealer['name'],
                        "city": dealer['city'],
                        "state": dealer['state'],
                        "region": dealer['region']
                    }
                }
                geojson["features"].append(feature)

        geojson_path = f"{output_dir}/bpcl_complete_dealerships_{self.timestamp}.geojson"
        with open(geojson_path, 'w') as f:
            json.dump(geojson, f)
        print(f"    ✓ {geojson_path} ({len(geojson['features'])} features)")

        # Export Summary
        print(f"  Generating summary...")
        summary = {
            'timestamp': self.timestamp,
            'total_dealerships': len(self.all_dealerships),
            'unique_states': len(set(d.get('state', 'Unknown') for d in self.all_dealerships.values())),
            'unique_cities': len(set(d.get('city', 'Unknown') for d in self.all_dealerships.values())),
            'unique_regions': len(set(d.get('region', 'Unknown') for d in self.all_dealerships.values())),
            'region_breakdown': self.region_stats,
            'state_distribution': self._get_state_distribution(),
            'region_distribution': self._get_region_distribution(),
            'data_quality': {
                'records_with_address': sum(1 for d in self.all_dealerships.values() if d.get('address')),
                'records_with_customer_code': sum(1 for d in self.all_dealerships.values() if d.get('customer_code'))
            }
        }

        summary_path = f"{output_dir}/bpcl_complete_dealerships_summary_{self.timestamp}.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"    ✓ {summary_path}")

        print(f"\n✅ Export complete to {output_dir}/")
        return output_dir

    def _get_state_distribution(self):
        """Get dealership distribution by state."""
        dist = {}
        for dealer in self.all_dealerships.values():
            state = dealer.get('state', 'Unknown')
            dist[state] = dist.get(state, 0) + 1
        return dict(sorted(dist.items(), key=lambda x: x[1], reverse=True))

    def _get_region_distribution(self):
        """Get dealership distribution by region."""
        dist = {}
        for dealer in self.all_dealerships.values():
            region = dealer.get('region', 'Unknown')
            dist[region] = dist.get(region, 0) + 1
        return dict(sorted(dist.items(), key=lambda x: x[1], reverse=True))

    def print_summary(self):
        """Print final extraction summary."""
        print("\n" + "="*80)
        print("📊 BPCL COMPLETE DEALERSHIP DATABASE SUMMARY")
        print("="*80)

        if not self.all_dealerships:
            print("✗ No dealerships extracted")
            return

        print(f"\n✅ EXTRACTION COMPLETE!")
        print(f"\n   Total Dealerships: {len(self.all_dealerships)}")

        state_dist = self._get_state_distribution()
        region_dist = self._get_region_distribution()

        print(f"   Unique States: {len(state_dist)}")
        print(f"   Unique Cities: {len(set(d.get('city', 'Unknown') for d in self.all_dealerships.values()))}")
        print(f"   Unique Regions: {len(region_dist)}")

        print(f"\n   Region Distribution:")
        for region, count in region_dist.items():
            print(f"   • {region}: {count}")

        print(f"\n   Top States:")
        for state, count in list(state_dist.items())[:10]:
            print(f"   • {state}: {count}")

        print(f"\n   Data Completeness:")
        total = len(self.all_dealerships)
        print(f"   • Names: {total} / {total} (100%)")
        print(f"   • Addresses: {sum(1 for d in self.all_dealerships.values() if d.get('address'))} / {total}")
        print(f"   • Cities: {sum(1 for d in self.all_dealerships.values() if d.get('city'))} / {total}")
        print(f"   • Customer Codes: {sum(1 for d in self.all_dealerships.values() if d.get('customer_code'))} / {total}")

    def run_extraction(self):
        """Run complete extraction pipeline."""
        print("\n" + "="*80)
        print("🚀 BPCL REGIONAL DEALERSHIP EXTRACTION")
        print("="*80)
        print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Extract by regions
        self.extract_all_regions()

        # Enrich data
        self.enrich_dealership_data()

        # Export
        self.export_complete_database()

        # Print summary
        self.print_summary()

        print(f"\nEnd time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80 + "\n")


def main():
    """Main execution."""
    extractor = BPCLRegionalExtractor()
    extractor.run_extraction()


if __name__ == "__main__":
    main()
