"""Notebook dashboard and optional external catalog lookups."""
import base64
import html
from io import BytesIO
from urllib.parse import urlencode
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from astropy.coordinates import SkyCoord
from astropy.visualization import ImageNormalize, ZScaleInterval, AsinhStretch
import astropy.units as u
from IPython.display import display, HTML

from .inputs import resolve_target

ALL_PANELS = ("rubin", "legacy", "skybot", "ned", "simbad", "tns")
_BUTLERS = {}


def query_tns_neighbors(center, radius_arcsec, credentials):
    """TNS Search API: return names within the cone, without fetching photometry.

    credentials: dict with api_key, bot_id, bot_name. No credentials are saved.
    Result names are not guaranteed physical associations with the candidate.
    """
    import json
    import requests
    marker = "tns_marker" + json.dumps({
        "tns_id": int(credentials["bot_id"]), "type": "bot",
        "name": credentials["bot_name"],
    })
    # TNS expects sexagesimal coordinates and an explicitly unit-tagged radius.
    payload = {
        "ra": center.ra.to_string(unit=u.hourangle, sep=":", precision=6),
        "dec": center.dec.to_string(unit=u.deg, sep=":", precision=5, alwayssign=True),
        "radius": float(radius_arcsec), "units": "arcsec",
    }
    response = requests.post(
        "https://www.wis-tns.org/api/get/search",
        headers={"User-Agent": marker},
        data={"api_key": credentials["api_key"], "data": json.dumps(payload)},
        timeout=45,
    )
    response.raise_for_status()
    body = response.json()
    if str(body.get("id_code")) != "200":
        # Do not print the response, which could contain authentication details.
        raise RuntimeError(f"TNS API returned code {body.get('id_code', 'unknown')}")
    data = body.get("data")
    # Handle both direct lists and lists wrapped in a reply object.
    matches = data.get("reply") if isinstance(data, dict) else data
    if not isinstance(matches, list):
        raise RuntimeError("Unexpected TNS response structure; not a no-match result")
    rows = []
    for match in matches:
        name = str(match.get("objname", ""))
        rows.append({
            "name": f"{match.get('prefix', match.get('name_prefix', ''))} {name}".strip(),
            "TNS_ID": match.get("objid", match.get("id")),
            "url": "https://www.wis-tns.org/object/" + name,
        })
    return pd.DataFrame(rows, columns=["name", "TNS_ID", "url"])


def plot_inspection_light_curves(lc, object_id, zoom_width_days=1.0, *, show=True):
    """Full and zoomed curves; peak = largest |flux| among usable plotted points.

    All bands compete in flux units, not S/N. The zoom has its own flux scale.
    Its x-axis fits the selected measurements rather than the entire selection window.
    zoom_width_days is the total window width, centered on the selected visit.
    Set show=False to save or display the returned figure yourself. The second
    return value records the peak visit and window bounds for later lookups.
    """
    if not np.isfinite(zoom_width_days) or zoom_width_days <= 0:
        raise ValueError("zoom_width_days must be finite and positive")
    names = ["band", "midpointMjdTai", "psfDiffFlux", "psfDiffFluxErr_corrected"]
    points = lc[names].copy()
    for col in names[1:]:
        points[col] = points[col].to_numpy(dtype=float, na_value=np.nan)
    # Keep signed fluxes, but exclude points that cannot be drawn with valid error bars.
    valid = (np.isfinite(points[names[1:]]).all(axis=1)
             & (points[names[3]] > 0) & points["band"].isin(list("ugrizy")))
    points = points.loc[valid].reset_index(drop=True)
    if points.empty:
        raise ValueError("No usable light-curve measurements to plot")
    peak = points.iloc[np.argmax(np.abs(points["psfDiffFlux"].to_numpy()))]
    peak_time = float(peak["midpointMjdTai"])
    half_width = zoom_width_days / 2
    lo, hi = peak_time-half_width, peak_time+half_width
    colors = dict(u="purple", g="green", r="red", i="darkorange", z="saddlebrown", y="black")
    fig, axes = plt.subplots(1, 2, figsize=(15, 4), layout="constrained")
    for band in "ugrizy":
        full = points.loc[points["band"] == band].sort_values("midpointMjdTai")
        zoom = full.loc[full["midpointMjdTai"].between(lo, hi)]
        for ax, subset in zip(axes, (full, zoom)):
            if not subset.empty:
                ax.errorbar(subset["midpointMjdTai"], subset["psfDiffFlux"],
                            yerr=subset["psfDiffFluxErr_corrected"], fmt="o", ms=3,
                            capsize=2, color=colors[band], label=band, alpha=.8)
    for ax in axes:
        ax.axhline(0, color="gray", lw=.8, ls="--")
        ax.axvline(peak_time, color="gray", lw=.8, ls=":")
        ax.set(xlabel="MJD (TAI)", ylabel="PSF difference flux")
        ax.ticklabel_format(axis="x", style="plain", useOffset=False)
        ax.legend(title="Band", ncol=3, fontsize=8)
    axes[0].axvspan(lo, hi, color="gray", alpha=.12)
    axes[0].set_title("Full light curve (shaded region = zoom)")
    # Plot only the selected window; let Matplotlib fit the observed times.
    axes[1].plot(peak_time, peak["psfDiffFlux"], marker="o", ms=10,
                 markerfacecolor="none", markeredgecolor="black", linestyle="none")
    axes[1].set_title(f'{zoom_width_days:g}-day window around largest |flux| '
                      f'({peak["band"]} band)')
    fig.suptitle(f"diaObjectId: {object_id}")
    if show:
        plt.show()
    return fig, {"mjd": peak_time, "band": str(peak["band"]),
                 "flux": float(peak["psfDiffFlux"]), "window_mjd": (lo, hi)}


def query_skybot_neighbors(center, epoch_utc, radius_arcsec=2.0, location="X05"):
    """Known Solar System objects at a visit epoch, as seen from Rubin (X05).

    Pass astropy Time; explicitly use UTC. Returns all SkyBoT columns plus a
    separation_arcsec column. Empty results and service errors remain distinct.
    No geocentric fallback is used if the observatory code fails.
    """
    from astroquery.imcce import Skybot
    if not np.isfinite(radius_arcsec) or not 0 < radius_arcsec <= 36000:
        raise ValueError("SkyBoT radius must be positive and at most 10 degrees")
    skybot = Skybot()
    skybot.TIMEOUT = 45
    try:
        table = skybot.cone_search(
            center, radius_arcsec*u.arcsec, epoch_utc.utc,
            location=location, find_planets=True, find_asteroids=True,
            find_comets=True, cache=True,
        )
    except RuntimeError as exc:
        # Astroquery represents a successful, empty SkyBoT search as an exception.
        if str(exc).strip().startswith(
            "No solar system object was found in the requested FOV"
        ):
            from astropy.table import QTable
            return QTable()
        raise
    if table is not None and len(table):
        table = table.copy()
        # Recompute angular separation from the returned ephemeris coordinates.
        predicted = SkyCoord(table["RA"], table["DEC"], unit=(u.deg, u.deg))
        table["separation_arcsec"] = center.separation(predicted).arcsec
        table.sort("separation_arcsec")
    return table


def inspect_transient(object_id, *, object_table, lightcurves=None, catalog=None,
                      panels=(), observatory_code="X05",
                      coadd_band="i", cutout_size_arcsec=60.,
                      neighbor_radius_arcsec=2., zoom_width_days=1.,
                      repository="dp2", collections="dp2",
                      tns_credentials=None, skybot_radius_arcsec=None):
    """Plot a candidate and optionally show images and nearby catalog entries.

    Pass a candidate table containing the ID and ICRS position, plus one source
    of photometry: a long-format table, a nested light curve in the candidate
    row, or an LSDB catalog. See the README for column names and units.

    With panels=(), only the light curve is displayed and no external archive is
    queried (an explicitly supplied LSDB catalog may still read remote data).
    Use panels=ALL_PANELS for the complete dashboard. SkyBoT uses the largest
    absolute-flux plotted visit, converted from MJD TAI to UTC. Optional panel
    failures are recorded in result["errors"].
    The result includes the original candidate row, the figure and peak
    metadata, and data or links for the enabled panels. Angular sizes and
    search radii are in arcseconds; SkyBoT inherits the neighbor radius unless
    given a separate radius.
    """
    if coadd_band not in tuple("ugrizy"):
        raise ValueError("coadd_band must be one of u,g,r,i,z,y")
    if not all(np.isfinite(v) and v > 0 for v in (
        cutout_size_arcsec, neighbor_radius_arcsec, zoom_width_days
    )):
        raise ValueError("Cutout size, neighbor radius, and zoom width must be finite and positive")
    panels = frozenset(panels)
    if unknown := panels.difference(ALL_PANELS):
        raise ValueError(f"Unknown panels: {sorted(unknown)}")
    oid, obj, lc = resolve_target(object_id, object_table, lightcurves=lightcurves, catalog=catalog)
    center = SkyCoord(float(obj['ra'])*u.deg, float(obj['dec'])*u.deg, frame='icrs')
    ra, dec = center.ra.deg, center.dec.deg
    result = {'object': obj, 'errors': {}}
    print(f'diaObjectId: {oid}\nRA={ra:.8f} deg, Dec={dec:.8f} deg')

    if "rubin" in panels:
        # Rubin cutout: request a small native CellCoadd subset.
        try:
            from lsst.daf.butler import Butler
            from lsst.images import Box
            # Reuse the Butler connection across candidates in the same notebook.
            cache_key = (repository, str(collections))
            if cache_key not in _BUTLERS:
                _BUTLERS[cache_key] = Butler(repository, collections=collections)
            butler = _BUTLERS[cache_key]
            refs = list(butler.query_datasets(
                'deep_coadd',
                where='band.name = :band AND patch.region OVERLAPS POINT(:ra, :dec)',
                bind={'band': coadd_band, 'ra': ra, 'dec': dec},
                order_by=['tract', 'patch', 'band'],
            ))
            if not refs:
                raise LookupError(f'No {coadd_band}-band deep_coadd covers this position')
            cutout = None
            failures = []
            # A position can overlap multiple patches; try another if the cutout hits an edge.
            for ref in refs:
                try:
                    projection = butler.get('deep_coadd.sky_projection', dataId=ref.dataId)
                    xy = projection.sky_to_pixel(center)
                    # Determine angular pixel scale locally, without assuming 0.2 arcsec/pixel.
                    neighbor = projection.sky_to_pixel(center.directional_offset_by(0*u.deg, 1*u.arcsec))
                    pixels_per_arcsec = np.hypot(neighbor.x-xy.x, neighbor.y-xy.y)
                    if not np.isfinite(pixels_per_arcsec) or pixels_per_arcsec <= 0:
                        raise ValueError('Invalid local coadd pixel scale')
                    half = max(1, int(np.ceil(cutout_size_arcsec*pixels_per_arcsec/2)))
                    x, y = int(round(xy.x)), int(round(xy.y))
                    bbox = Box.factory[y-half:y+half+1, x-half:x+half+1]
                    cutout = butler.get(ref, parameters={'bbox': bbox})
                    selected_ref = ref
                    break
                except Exception as exc:
                    failures.append(f'{ref.dataId}: {type(exc).__name__}: {exc}')
            if cutout is None:
                raise RuntimeError('No overlapping patch supplied the requested cutout. '
                                   'Try a smaller cutout. ' + '; '.join(failures))
            image = np.asarray(cutout.image.array, dtype=float)
            finite = image[np.isfinite(image)]
            if not finite.size:
                raise ValueError("Coadd contains no finite pixels")
            norm = ImageNormalize(finite, interval=ZScaleInterval(), stretch=AsinhStretch())
            # Render only the Rubin image locally; the Legacy image loads in the browser.
            fig, ax = plt.subplots(figsize=(4, 4), dpi=120)
            ax.imshow(image, origin="lower", cmap="gray", norm=norm, interpolation="nearest")
            # Convert parent-patch pixels to coordinates relative to the cutout.
            ax.plot(xy.x-cutout.bbox.x.start, xy.y-cutout.bbox.y.start,
                    "+", color="red", ms=15, mew=1.5)
            ax.set_axis_off()
            fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
            with BytesIO() as buffer:
                fig.savefig(buffer, format="png", dpi=120)
                coadd_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
            plt.close(fig)
            rubin_panel = f'<img src="{coadd_uri}" style="width:100%;display:block">'
            result.update(coadd=cutout, coadd_data_id=selected_ref.dataId)
        except Exception as exc:
            result["errors"]["Rubin coadd"] = f"{type(exc).__name__}: {exc}"
            rubin_panel = '<p>' + html.escape(result["errors"]["Rubin coadd"]) + '</p>'

    if "legacy" in panels:
        params = dict(ra=ra, dec=dec, layer="ls-dr10", size=256,
                      pixscale=cutout_size_arcsec/256)
        image_url = "https://www.legacysurvey.org/viewer/jpeg-cutout?" + urlencode(params)
        viewer_url = "https://www.legacysurvey.org/viewer/?" + urlencode(
            dict(ra=ra, dec=dec, layer="ls-dr10", zoom=16))
        legacy_panel = (
            '<div style="position:relative">'
            f'<img src="{html.escape(image_url, quote=True)}" style="width:100%;display:block" '
            'alt="Legacy cutout unavailable: check service access or sky coverage">'
            '<span style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);'
            'color:red;font-size:28px;pointer-events:none">+</span></div>'
        )

    image_panels = []
    if "rubin" in panels:
        image_panels.append(f"<div><h4>Rubin {coadd_band}-band coadd</h4>{rubin_panel}</div>")
    if "legacy" in panels:
        image_panels.append(f"<div><h4>Legacy Survey DR10</h4>{legacy_panel}</div>")
        result.update(legacy_image_url=image_url, legacy_viewer_url=viewer_url)
    if image_panels:
        columns = len(image_panels)
        footnote = (
            f'<a href="{html.escape(viewer_url, quote=True)}" target="_blank" rel="noopener">'
            "Open Legacy viewer</a>." if "legacy" in panels else ""
        )
        display(HTML(
            f'<div style="display:grid;grid-template-columns:repeat({columns}, minmax(0,1fr));'
            'gap:16px;max-width:900px;align-items:start">'
            + "".join(image_panels) + "</div>"
            f"<p>Width: approximately {cutout_size_arcsec:g} arcsec. "
            "Target marked in red. Native image orientations may differ. "
            f"{footnote}</p>"
        ))

    # Full and one-day zoomed light curves side by side below the images.
    fig, peak = plot_inspection_light_curves(
        lc, oid, zoom_width_days=zoom_width_days)
    result["light_curve_figure"] = fig
    result["light_curve_peak"] = peak

    if "skybot" in panels:
        # One ephemeris search at the SAME absolute-flux peak used by the zoom.
        from astropy.time import Time
        epoch_utc = Time(peak["mjd"], format="mjd", scale="tai").utc
        skybot_radius = (neighbor_radius_arcsec if skybot_radius_arcsec is None
                         else skybot_radius_arcsec)
        result.update(skybot=None, skybot_status="not_queried",
                      skybot_epoch_utc=epoch_utc, skybot_observatory=observatory_code,
                      skybot_radius_arcsec=skybot_radius)
        print(f"\nSkyBoT: {skybot_radius:g} arcsec, observer {observatory_code}, {epoch_utc.isot} UTC")
        print(f'Peak visit: MJD {peak["mjd"]:.9f} TAI, {peak["band"]} band, flux={peak["flux"]:g}')
        try:
            table = query_skybot_neighbors(center, epoch_utc, skybot_radius, location=observatory_code)
            result["skybot"] = table
            result["skybot_status"] = "queried"
            if table is None or len(table) == 0:
                print("No known Solar System objects returned at this epoch.")
            else:
                columns = ["separation_arcsec", "Number", "Name", "Type", "V",
                           "posunc", "RA_rate", "DEC_rate", "RA", "DEC"]
                display(table[[c for c in columns if c in table.colnames]])
                print("V is predicted V-band magnitude; motion rates are arcsec/hour. "
                      "A nearby prediction flags possible contamination, not a confirmed association.")
        except Exception as exc:
            result["skybot_status"] = "failed"
            result["errors"]["SkyBoT"] = f"{type(exc).__name__}: {exc}"
            print("SkyBoT query failed (not a no-match result):", result["errors"]["SkyBoT"])

    # Query each catalog independently so an outage does not hide other results.
    radius = neighbor_radius_arcsec*u.arcsec
    for service in ['NED', 'SIMBAD']:
        if service.lower() not in panels:
            continue
        print(f'\n{service}: objects within {neighbor_radius_arcsec:g} arcsec')
        try:
            if service == 'NED':
                from astroquery.ipac.ned import Ned
                Ned.TIMEOUT = 45
                table = Ned.query_region(center, radius=radius)
            else:
                from astroquery.simbad import Simbad
                simbad = Simbad()
                simbad.TIMEOUT = 45
                simbad.ROW_LIMIT = -1
                simbad.add_votable_fields('otype')
                table = simbad.query_region(center, radius=radius)
            if table is None or len(table) == 0:
                print('No catalog entries returned.')
                result[service.lower()] = table
                continue
            # Modern SIMBAD uses decimal-degree ra/dec; older outputs use sexagesimal.
            lookup = {c.lower(): c for c in table.colnames}
            coords = None
            if 'ra' in lookup and 'dec' in lookup:
                rc, dc = lookup['ra'], lookup['dec']
                if table[rc].dtype.kind in 'iuf':
                    coords = SkyCoord(ra=np.asarray(table[rc], dtype=float) * u.deg,
                                      dec=np.asarray(table[dc], dtype=float) * u.deg)
                else:
                    coords = SkyCoord(table[rc], table[dc], unit=(u.hourangle, u.deg))
            elif 'ra-s' in lookup and 'dec-s' in lookup:
                coords = SkyCoord(table[lookup['ra-s']], table[lookup['dec-s']],
                                  unit=(u.hourangle, u.deg))
            if coords is not None:
                table['separation_arcsec'] = center.separation(coords).arcsec
                table.sort('separation_arcsec')
            preferred = (['Object Name', 'Type', 'RA', 'DEC', 'RA-s', 'DEC-s',
                          'Redshift', 'Redshift Flag', 'Magnitude and Filter']
                         if service == 'NED' else ['main_id', 'MAIN_ID', 'otype', 'OTYPE',
                                                   'ra', 'dec', 'RA', 'DEC'])
            cols = (['separation_arcsec'] if 'separation_arcsec' in table.colnames else [])
            cols += [c for c in preferred if c in table.colnames]
            display(table[cols] if cols else table)
            result[service.lower()] = table
        except Exception as exc:
            result['errors'][service] = f'{type(exc).__name__}: {exc}'
            print(f'{service} query failed (not a no-match result):', result['errors'][service])
    if "tns" in panels:
        # TNS uses authenticated POST for reading; no reports are submitted.
        import os
        tns_url = "https://www.wis-tns.org/search?" + urlencode({
            "ra": center.ra.to_string(unit=u.hourangle, sep=":", precision=6),
            "decl": center.dec.to_string(unit=u.deg, sep=":", precision=5, alwayssign=True),
            "radius": neighbor_radius_arcsec, "coords_unit": "arcsec",
            "isTNS_AT": "all", "num_page": 50,
        })
        result["tns_search_url"] = tns_url
        result["tns"] = None
        result["tns_status"] = "not_queried"
        print(f"\nTNS: objects within {neighbor_radius_arcsec:g} arcsec")
        display(HTML(f'<a href="{html.escape(tns_url, quote=True)}" target="_blank" '
                     'rel="noopener">Open this cone search in TNS</a>'))
        credentials = tns_credentials if tns_credentials is not None else {
            "api_key": os.environ.get("TNS_API_KEY"),
            "bot_id": os.environ.get("TNS_BOT_ID"),
            "bot_name": os.environ.get("TNS_BOT_NAME"),
        }
        if not all(credentials.get(k) for k in ("api_key", "bot_id", "bot_name")):
            print("TNS not queried automatically: configure bot credentials or use the link.")
        else:
            try:
                table = query_tns_neighbors(center, neighbor_radius_arcsec, credentials)
                result["tns"] = table
                result["tns_status"] = "queried"
                if table.empty:
                    print("No TNS entries returned.")
                else:
                    display(table)
            except Exception as exc:
                result["tns_status"] = "failed"
                # Keep exception type only: never expose credentials through service errors.
                result["errors"]["TNS"] = type(exc).__name__
                print("TNS query failed (not a no-match result):", type(exc).__name__,
                      "— check credentials, service availability, and request limits.")

    return result

