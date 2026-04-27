/*
 * CrisisNexus Geospatial Engine
 * Fast C library for haversine distance calculations and nearest-unit routing.
 * Called from Python via ctypes for performance-critical dispatch logic.
 */

#include <math.h>
#include <stdlib.h>
#include <float.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define EARTH_RADIUS_KM 6371.0
#define DEG_TO_RAD(d) ((d) * M_PI / 180.0)

/* Haversine formula — returns great-circle distance in kilometers */
double haversine(double lat1, double lon1, double lat2, double lon2) {
    double dlat = DEG_TO_RAD(lat2 - lat1);
    double dlon = DEG_TO_RAD(lon2 - lon1);
    double rlat1 = DEG_TO_RAD(lat1);
    double rlat2 = DEG_TO_RAD(lat2);
    double a = sin(dlat / 2.0) * sin(dlat / 2.0)
             + cos(rlat1) * cos(rlat2)
             * sin(dlon / 2.0) * sin(dlon / 2.0);
    double c = 2.0 * atan2(sqrt(a), sqrt(1.0 - a));
    return EARTH_RADIUS_KM * c;
}

/*
 * Find index of nearest available unit to an incident.
 * lats / lons are arrays of length n.
 * Returns -1 if n == 0.
 */
int find_nearest_unit(double inc_lat, double inc_lon,
                      double *lats, double *lons, int n) {
    if (n <= 0) return -1;
    int nearest = 0;
    double min_dist = haversine(inc_lat, inc_lon, lats[0], lons[0]);
    for (int i = 1; i < n; i++) {
        double d = haversine(inc_lat, inc_lon, lats[i], lons[i]);
        if (d < min_dist) {
            min_dist = d;
            nearest = i;
        }
    }
    return nearest;
}

/*
 * Compute a dispatch priority score (lower = higher priority).
 * Factors: distance (km), severity (1=P1 highest, 3=P3 lowest), unit_load (0-1).
 * Returns a composite score for ranking multiple candidate units.
 */
double dispatch_score(double distance_km, int severity, double unit_load) {
    double sev_weight = (severity == 1) ? 3.0 : (severity == 2) ? 2.0 : 1.0;
    return (distance_km * 0.5) + (unit_load * 20.0) - (sev_weight * 5.0);
}

/*
 * Estimate ETA in minutes given distance in km and average speed km/h.
 * Default emergency vehicle speed: 60 km/h (adjustable).
 */
double estimate_eta_minutes(double distance_km, double speed_kmh) {
    if (speed_kmh <= 0.0) speed_kmh = 60.0;
    return (distance_km / speed_kmh) * 60.0;
}

/*
 * Compute coverage radius in km for a given number of units and target density.
 * Simple model: sqrt(area / units) — used for Voronoi-style zone sizing.
 */
double coverage_radius(double area_sq_km, int num_units) {
    if (num_units <= 0) return 0.0;
    return sqrt(area_sq_km / (double)num_units) * 0.5;
}

/*
 * Batch distance computation: fills `out_distances` array with distances
 * from a single point to each of n targets.
 */
void batch_distances(double src_lat, double src_lon,
                     double *tgt_lats, double *tgt_lons, int n,
                     double *out_distances) {
    for (int i = 0; i < n; i++) {
        out_distances[i] = haversine(src_lat, src_lon, tgt_lats[i], tgt_lons[i]);
    }
}
