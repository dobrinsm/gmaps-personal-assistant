"""Unit tests for backend.main canonical place extraction (A1)."""
import io
import csv

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from main import _extract_geojson_features, _parse_csv_rows  # noqa: E402


class TestGeoJsonExtraction:
    def test_extracts_takeout_geo_shape(self):
        features = [{
            "properties": {
                "location": {
                    "name": "Bloom Coffee",
                    "address": "ul. Veslets 23, Sofia",
                    "geo": {"latitude": 42.6975, "longitude": 23.3242},
                }
            }
        }]
        places = _extract_geojson_features(features)
        assert places[0]["name"] == "Bloom Coffee"
        assert places[0]["lat"] == 42.6975
        assert places[0]["lng"] == 23.3242

    def test_extracts_geojson_point_geometry(self):
        features = [{
            "properties": {"name": "Point Place"},
            "geometry": {"coordinates": [23.32, 42.69]},
        }]
        places = _extract_geojson_features(features)
        assert places[0]["lat"] == 42.69
        assert places[0]["lng"] == 23.32

    def test_no_coords_still_extracted(self):
        features = [{"properties": {"location": {"name": "No Geo Place"}}}]
        places = _extract_geojson_features(features)
        assert places[0]["name"] == "No Geo Place"
        assert "lat" not in places[0]
        assert "lng" not in places[0]

    def test_malformed_coordinates_do_not_crash(self):
        features = [{
            "properties": {"name": "Bad"},
            "geometry": {"coordinates": ["not-a-number", None]},
        }]
        places = _extract_geojson_features(features)
        assert places[0]["name"] == "Bad"
        assert "lat" not in places[0]

    def test_none_features_returns_empty(self):
        assert _extract_geojson_features(None) == []


class TestCsvExtraction:
    def test_takeout_csv_preserves_lat_lng(self):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["Title", "Address", "Note", "Lat", "Lng"])
        w.writeheader()
        w.writerow({"Title": "Sputnik Bar", "Address": "bul. Yanko Sakazov 17, Sofia",
                    "Note": "retro cocktails", "Lat": "42.6889", "Lng": "23.3307"})
        places = _parse_csv_rows(buf.getvalue())
        assert places[0]["name"] == "Sputnik Bar"
        assert places[0]["lat"] == 42.6889
        assert places[0]["lng"] == 23.3307

    def test_csv_without_coords_omits_keys(self):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["Title", "Address"])
        w.writeheader()
        w.writerow({"Title": "No Coords Cafe", "Address": "somewhere"})
        places = _parse_csv_rows(buf.getvalue())
        assert places[0]["name"] == "No Coords Cafe"
        assert "lat" not in places[0]

    def test_rows_without_title_skipped(self):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["Title", "Address"])
        w.writeheader()
        w.writerow({"Title": "", "Address": "x"})
        assert _parse_csv_rows(buf.getvalue()) == []

    def test_bad_coords_do_not_crash(self):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["Title", "Lat", "Lng"])
        w.writeheader()
        w.writerow({"Title": "Weird", "Lat": "abc", "Lng": "xyz"})
        places = _parse_csv_rows(buf.getvalue())
        assert "lat" not in places[0]
